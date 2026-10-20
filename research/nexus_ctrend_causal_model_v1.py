"""Causal CS-C-ENet derivative on caller-supplied, already observed snapshots.

This module neither reads market data nor simulates returns. It is a derivative,
not a numerical replication of the MATLAB program. In particular, eligibility
and ranks are formed before historical labels are inspected, every training week
must have ten usable labels, and a constant cross-section receives rank zero.
All times are integer Unix epoch milliseconds, supplied explicitly by the caller.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import platform
import warnings

import numpy as np
import scipy
from scipy.stats import rankdata
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import ElasticNet


FEATURES = 28
HISTORY_WEEKS = 52
MIN_CAP = 1_000_000.0
MIN_FIT_ASSETS = 10
MIN_CURRENT_ASSETS = 25
MIN_QUINTILE_ASSETS = 5
L1_RATIO = 0.5
LAMBDA_COUNT = 200
LAMBDA_RATIO = 1e-4
SOLVER_TOL = 1e-8
SOLVER_MAX_ITER = 100_000


class ForecastUnavailable(RuntimeError):
    """Known information cannot support the specified learned portfolio."""


@dataclass(frozen=True)
class Forecast:
    scores: np.ndarray
    members: tuple[int, ...]
    selected_features: tuple[int, ...]
    diagnostics: dict


def _numeric_array(value, name: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.dtype.kind not in "iuf":
        raise ValueError(f"{name} must contain real numeric observations")
    out = np.array(raw, dtype=np.float64, copy=True)
    if np.isinf(out).any():
        raise ValueError(f"{name} contains infinite observations")
    return out


def _mask(value, shape: tuple, name: str) -> np.ndarray:
    if value is None:
        return np.ones(shape, dtype=bool)
    out = np.asarray(value)
    if out.shape != shape or out.dtype.kind != "b":
        raise ValueError(f"{name} must be a Boolean array of shape {shape}")
    return out.copy()


def _time(value, name: str) -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise ValueError(f"{name} must be an integer epoch millisecond")
    number = int(value)
    if number < 0 or number > np.iinfo(np.int64).max:
        raise ValueError(f"{name} is outside the supported epoch range")
    return number


def _times(value, shape: tuple, name: str) -> np.ndarray:
    raw = np.asarray(value)
    if raw.shape != shape or raw.dtype.kind not in "iu":
        raise ValueError(f"{name} must be an integer epoch-millisecond array of shape {shape}")
    # Validate before converting unsigned integers, which could otherwise wrap.
    if np.any(raw > np.iinfo(np.int64).max) or np.any(raw < 0):
        raise ValueError(f"{name} is outside the supported epoch range")
    out = raw.astype(np.int64, copy=True)
    if np.any(out[1:] <= out[:-1]):
        raise ValueError(f"{name} must be strictly chronological")
    return out


def _rank_snapshot(features: np.ndarray, caps: np.ndarray, known: np.ndarray):
    """Rank using only the as-of snapshot; there is deliberately no label input."""
    eligible = known & np.isfinite(caps) & (caps >= MIN_CAP)
    eligible &= np.isfinite(features).all(axis=1)
    ranked = np.full(features.shape, np.nan, dtype=np.float64)
    if eligible.any():
        for j in range(FEATURES):
            values = features[eligible, j]
            if np.all(values == values[0]):
                ranked[eligible, j] = 0.0
            else:
                ranks = rankdata(values, method="average")
                # Match the original rank/max(rank) convention in nonconstant
                # cross-sections; average ties can leave the bottom above -.5.
                ranked[eligible, j] = (ranks - 1) / (ranks.max() - 1) - 0.5
    return ranked, eligible


def _array_digest(array: np.ndarray) -> str:
    return hashlib.sha256(np.asarray(array, dtype="<f8").tobytes(order="C")).hexdigest()


def _select_forecasts(predictions, target, weights):
    """Weighted training-only scaling and the fixed 200-point AICc path."""
    weights = weights / weights.sum()
    means = np.average(predictions, axis=0, weights=weights)
    centered = predictions - means
    scales = np.sqrt(np.average(centered * centered, axis=0, weights=weights))
    active = scales > np.finfo(float).eps * np.maximum(1.0, np.abs(means))
    if not active.any():
        raise ForecastUnavailable("No nonconstant historical univariate forecasts")
    x = np.asfortranarray(centered[:, active] / scales[active])
    ymean = float(np.average(target, weights=weights))
    centered_y = target - ymean
    alpha_max = float(np.max(np.abs(x.T @ (weights * centered_y))) / L1_RATIO)
    if not np.isfinite(alpha_max) or alpha_max <= 0:
        raise ForecastUnavailable("No positive regularization path or learned signal")
    lambdas = np.geomspace(alpha_max, alpha_max * LAMBDA_RATIO, LAMBDA_COUNT)
    solver = ElasticNet(
        alpha=float(lambdas[0]), l1_ratio=L1_RATIO, fit_intercept=True,
        max_iter=SOLVER_MAX_ITER, tol=SOLVER_TOL, selection="cyclic",
        warm_start=True, copy_X=True,
    )
    records = []
    best = None
    sample_count = len(target)
    for index, strength in enumerate(lambdas):
        solver.set_params(alpha=float(strength))
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ConvergenceWarning)
            solver.fit(x, target, sample_weight=weights)
        if any(issubclass(item.category, ConvergenceWarning) for item in caught):
            raise ForecastUnavailable(f"ElasticNet did not converge at path index {index}")
        if not np.isfinite(solver.coef_).all() or not np.isfinite(solver.dual_gap_):
            raise ForecastUnavailable("ElasticNet produced a nonfinite solution")
        fitted = solver.predict(x)
        mse = float(np.average((target - fitted) ** 2, weights=weights))
        df = int(np.count_nonzero(solver.coef_))
        # Original fEstRegPanelRegression AICc uses nonzero slopes as DF;
        # the fitted intercept is not added to that count.
        if mse < 0 or not np.isfinite(mse) or sample_count <= df + 1:
            raise ForecastUnavailable("AICc cannot be calculated for this fit")
        aicc = float(sample_count * np.log(max(mse, np.finfo(float).tiny))
                     + 2 * df * sample_count / (sample_count - df - 1))
        records.append({"lambda": float(strength), "weighted_mse": mse,
                        "df_nonzero_slopes": df, "aicc": aicc,
                        "iterations": int(solver.n_iter_),
                        "dual_gap": float(solver.dual_gap_)})
        if best is None or aicc < best[0]:
            best = (aicc, solver.coef_.copy(), float(solver.intercept_), index)
    coefficients = np.zeros(FEATURES)
    coefficients[active] = best[1] / scales[active]
    selected = np.flatnonzero(coefficients > 0)
    if not len(selected):
        raise ForecastUnavailable("AICc-selected model has no positive forecast coefficients")
    return selected, {
        "lambda_count": LAMBDA_COUNT, "lambda_ratio": LAMBDA_RATIO,
        "l1_ratio": L1_RATIO, "selected_path_index": best[3],
        "selected_lambda": records[best[3]]["lambda"], "selected_aicc": best[0],
        "training_weighted_means": means.tolist(),
        "training_weighted_scales": scales.tolist(),
        "selection_coefficients_raw": coefficients.tolist(),
        "selection_intercept_standardized": best[2],
        "constant_forecasts": np.flatnonzero(~active).tolist(),
        "path": records,
    }


def _quintiles(scores: np.ndarray, eligible: np.ndarray):
    values = scores[eligible]
    if len(values) < MIN_CURRENT_ASSETS:
        raise ForecastUnavailable("At least 25 as-of eligible assets are required")
    # MATLAB's exact/midpoint empirical quantile convention is type 5/Hazen,
    # not numpy's separately named 'midpoint' interpolation method.
    cuts = np.quantile(values, [0.2, 0.4, 0.6, 0.8], method="hazen")
    bins = np.searchsorted(cuts, values, side="left")
    indices = np.flatnonzero(eligible)
    groups = tuple(tuple(int(i) for i in indices[bins == j]) for j in range(5))
    if any(len(group) < MIN_QUINTILE_ASSETS for group in groups):
        raise ForecastUnavailable("Every score quintile must contain at least five assets")
    return groups, cuts


def fit_predict(history_features, history_returns, history_caps,
                current_features, current_caps, *, feature_times, label_times,
                decision_time: int, current_feature_time: int,
                history_eligible=None, current_eligible=None) -> Forecast:
    """Fit on exactly the last 52 known weekly rows and rank the current cohort.

    NaN features/caps make an asset ineligible as of that snapshot. A NaN past
    return removes only that asset's FIT observation, after ranks are fixed.
    Masks must themselves be known at their supplied feature times; the caller
    must attest source release times and historical asset identity separately.
    Training labels must end by the current feature snapshot. This generic
    numeric layer validates ordering; the controller must additionally enforce
    the specified Jan1-anchored weekly calendar and complete period durations.
    There is no current or future return argument. Unavailable forecasts raise;
    this function does not substitute a cash portfolio or economic zero return.
    """
    hf = _numeric_array(history_features, "history_features")
    hr = _numeric_array(history_returns, "history_returns")
    hc = _numeric_array(history_caps, "history_caps")
    cf = _numeric_array(current_features, "current_features")
    cc = _numeric_array(current_caps, "current_caps")
    if hf.ndim != 3 or hf.shape[2] != FEATURES:
        raise ValueError("history_features must have shape [T,N,28]")
    time_count, asset_count, _ = hf.shape
    if (hr.shape != (time_count, asset_count) or hc.shape != hr.shape
            or cf.shape != (asset_count, FEATURES) or cc.shape != (asset_count,)):
        raise ValueError("Feature, return and capitalization shapes do not agree")
    known = _mask(history_eligible, hr.shape, "history_eligible")
    current_known = _mask(current_eligible, cc.shape, "current_eligible")
    ft = _times(feature_times, (time_count,), "feature_times")
    lt = _times(label_times, (time_count,), "label_times")
    decision = _time(decision_time, "decision_time")
    current_time = _time(current_feature_time, "current_feature_time")
    if np.any(ft >= lt) or np.any(lt > decision) or current_time > decision:
        raise ValueError("Require feature_time < label_time <= decision_time and known current features")
    if np.any(lt > current_time) or np.any(ft >= current_time):
        raise ValueError("Historical labels must end by the current feature snapshot, with prior feature times")
    if time_count < HISTORY_WEEKS:
        raise ForecastUnavailable("Exactly 52 historical rows are needed for the rolling fit")
    start = time_count - HISTORY_WEEKS
    hf, hr, hc, known = hf[start:], hr[start:], hc[start:], known[start:]
    ft, lt = ft[start:], lt[start:]
    current_rank, current_membership = _rank_snapshot(cf, cc, current_known)
    if int(current_membership.sum()) < MIN_CURRENT_ASSETS:
        raise ForecastUnavailable("At least 25 as-of eligible assets are required")

    ranks = np.full(hf.shape, np.nan)
    eligible = np.zeros(hr.shape, dtype=bool)
    fit_masks = np.zeros(hr.shape, dtype=bool)
    coefficients = np.zeros((HISTORY_WEEKS, FEATURES, 2))
    targets, fit_weights = [], []
    target_means = []
    for week in range(HISTORY_WEEKS):
        ranks[week], eligible[week] = _rank_snapshot(hf[week], hc[week], known[week])
        # Past targets enter only here, after as-of eligibility and ranking.
        fitted = eligible[week] & np.isfinite(hr[week])
        fit_masks[week] = fitted
        if int(fitted.sum()) < MIN_FIT_ASSETS:
            raise ForecastUnavailable(f"Historical row {start + week} has fewer than ten fit assets")
        target_mean = float(np.mean(hr[week, fitted]))
        target = hr[week, fitted] - target_mean
        target_means.append(target_mean)
        # Normalize by the whole as-of eligible cohort, before missing labels
        # remove fit rows. WLS/ElasticNet subsequently normalize these weights.
        caps = hc[week, eligible[week]]
        cap_denominator = float(np.sum(caps / np.max(caps)))
        weights = (hc[week, fitted] / np.max(caps)) / cap_denominator
        if not np.isfinite(weights).all() or np.any(weights <= 0):
            raise ForecastUnavailable("Historical capitalization weights are not representable")
        root_weights = np.sqrt(weights)
        for j in range(FEATURES):
            design = np.column_stack((np.ones(int(fitted.sum())), ranks[week, fitted, j]))
            coefficients[week, j] = np.linalg.lstsq(
                design * root_weights[:, None], target * root_weights, rcond=None,
            )[0]
        targets.append(target)
        fit_weights.append(weights)
    mean_coefficients = coefficients.mean(axis=0)
    if not np.isfinite(mean_coefficients).all():
        raise ForecastUnavailable("Univariate historical coefficients are nonfinite")
    rank_panel = np.concatenate([ranks[t, fit_masks[t]] for t in range(HISTORY_WEEKS)])
    predictions = mean_coefficients[:, 0] + rank_panel * mean_coefficients[:, 1]
    selected, selection = _select_forecasts(
        predictions, np.concatenate(targets), np.concatenate(fit_weights),
    )
    raw_current = (mean_coefficients[selected, 0]
                   + current_rank[:, selected] * mean_coefficients[selected, 1])
    scores = np.mean(raw_current, axis=1)
    scores[~current_membership] = np.nan
    if not np.isfinite(scores[current_membership]).all():
        raise ForecastUnavailable("Current forecasts are nonfinite")
    groups, cutpoints = _quintiles(scores, current_membership)
    high = groups[-1]
    high_caps = cc[list(high)]
    weights = high_caps / np.max(high_caps)
    weights /= weights.sum()
    diagnostics = {
        "schema": "nexus.ctrend-causal-cs-c-enet.v1",
        "derivative_not_vendor_numerical_replication": True,
        "versions": {"python": platform.python_version(), "numpy": np.__version__,
                     "scipy": scipy.__version__, "sklearn": sklearn.__version__},
        "solver": {"name": "sklearn.linear_model.ElasticNet", "selection": "cyclic",
                   "tol": SOLVER_TOL, "max_iter": SOLVER_MAX_ITER,
                   "all_path_points_converged": True},
        "time_unit": "unix_epoch_milliseconds", "decision_time": decision,
        "current_feature_time": current_time, "feature_times": ft.tolist(),
        "label_times": lt.tolist(), "history_input_rows": time_count,
        "history_start_row": start, "history_rows_used": HISTORY_WEEKS,
        "historical_asof_counts": eligible.sum(axis=1).tolist(),
        "historical_fit_counts": fit_masks.sum(axis=1).tolist(),
        "training_rank_digest": _array_digest(ranks),
        "current_rank_digest": _array_digest(current_rank),
        "historical_target_centering": "unweighted_valid_fit_cross_section_mean",
        "historical_target_means": target_means,
        "mean_univariate_intercept_slope": mean_coefficients.tolist(),
        "current_eligible_indices": np.flatnonzero(current_membership).tolist(),
        "quintile_method": "hazen_type5", "quintile_cutpoints": cutpoints.tolist(),
        "quintile_members": [list(group) for group in groups],
        "informational_high_cap_weights": weights.tolist(),
        "selection": selection,
        "orders": 0, "paper_eligible": False, "live_enabled": False,
    }
    scores.setflags(write=False)
    return Forecast(scores=scores, members=high,
                    selected_features=tuple(int(j) for j in selected),
                    diagnostics=diagnostics)
