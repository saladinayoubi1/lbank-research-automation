from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import bybit_long_short_search_v4 as engine
import bybit_portfolio_search_v3 as market_utils


class ConsensusSearchError(RuntimeError):
    pass


def candidate_id(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def lag_return(close: np.ndarray, days: int) -> np.ndarray:
    periods = market_utils.bars(days)
    output = np.full_like(close, np.nan)
    output[periods:] = close[periods:] / close[:-periods] - 1.0
    return output


def realized_vol(close: np.ndarray, days: int) -> np.ndarray:
    return market_utils.realized_vol(close, days)


def enumerate_candidates(config: dict[str, Any]) -> list[dict[str, Any]]:
    search = config["search"]
    candidates: list[dict[str, Any]] = []
    for values in itertools.product(
        search["lookback_sets"],
        search["vote_pairs"],
        search["ema_pairs"],
        search["deadband"],
        search["short_scale"],
        search["fast_reversal"],
        search["market_mode"],
        search["vol_days"],
        search["target_vol"],
        search["rebalance_days"],
        search["vol_ratio_trigger"],
        search["high_vol_scale"],
    ):
        (
            lookbacks,
            votes,
            ema,
            deadband,
            short_scale,
            fast_reversal,
            market_mode,
            vol_days,
            target_vol,
            rebalance_days,
            vol_ratio_trigger,
            high_vol_scale,
        ) = values
        params = {
            "lookbacks": lookbacks,
            "long_vote": votes["long"],
            "short_vote": votes["short"],
            "ema_fast_days": ema["fast"],
            "ema_slow_days": ema["slow"],
            "deadband": deadband,
            "short_scale": short_scale,
            "fast_reversal": fast_reversal,
            "market_mode": market_mode,
            "vol_days": vol_days,
            "target_vol": target_vol,
            "rebalance_days": rebalance_days,
            "vol_ratio_trigger": vol_ratio_trigger,
            "high_vol_scale": high_vol_scale,
            "quantum": search["quantum"],
        }
        candidates.append({
            "id": candidate_id(params),
            "family": "consensus_regime",
            "params": params,
        })
    return candidates


def structural_key(candidate: dict[str, Any]) -> str:
    excluded = {
        "vol_days",
        "target_vol",
        "rebalance_days",
        "vol_ratio_trigger",
        "high_vol_scale",
        "quantum",
    }
    params = {
        key: value
        for key, value in candidate["params"].items()
        if key not in excluded
    }
    return json.dumps(params, sort_keys=True)


def structural_signal(
    market: dict[str, Any], candidate: dict[str, Any]
) -> np.ndarray:
    close = market["close"]
    params = candidate["params"]
    returns = np.stack(
        [lag_return(close, int(days)) for days in params["lookbacks"]],
        axis=2,
    )
    positive_votes = np.mean(returns > 0.0, axis=2)
    negative_votes = np.mean(returns < 0.0, axis=2)
    median_return = np.nanmedian(returns, axis=2)
    fast_return = lag_return(close, 30)

    fast = np.column_stack([
        pd.Series(close[:, asset]).ewm(
            span=market_utils.bars(int(params["ema_fast_days"])),
            adjust=False,
            min_periods=market_utils.bars(int(params["ema_fast_days"])),
        ).mean().to_numpy(float)
        for asset in range(close.shape[1])
    ])
    slow = np.column_stack([
        pd.Series(close[:, asset]).ewm(
            span=market_utils.bars(int(params["ema_slow_days"])),
            adjust=False,
            min_periods=market_utils.bars(int(params["ema_slow_days"])),
        ).mean().to_numpy(float)
        for asset in range(close.shape[1])
    ])
    ema_score = fast / slow - 1.0

    long_mask = (
        (positive_votes >= float(params["long_vote"]))
        & (median_return > float(params["deadband"]))
        & (ema_score > 0.0)
        & (fast_return > -float(params["fast_reversal"]))
    )
    short_mask = (
        (negative_votes >= float(params["short_vote"]))
        & (median_return < -float(params["deadband"]))
        & (ema_score < 0.0)
        & (fast_return < float(params["fast_reversal"]))
    )

    if params["market_mode"] == "breadth":
        market_momentum = np.nanmedian(median_return, axis=1)
        long_mask &= market_momentum[:, None] > 0.0
        short_mask &= market_momentum[:, None] < 0.0
    elif params["market_mode"] != "asset":
        raise ConsensusSearchError(
            f"Unsupported market mode: {params['market_mode']}"
        )

    signal = np.zeros_like(close, dtype=float)
    signal[long_mask] = 1.0
    signal[short_mask] = -float(params["short_scale"])
    signal[~np.isfinite(ema_score)] = 0.0
    return signal


def construct_weights(
    signal: np.ndarray,
    long_vol: np.ndarray,
    fast_vol: np.ndarray,
    candidate: dict[str, Any],
) -> np.ndarray:
    params = candidate["params"]
    active = np.abs(signal) > 0.0
    inverse = np.divide(
        1.0,
        long_vol,
        out=np.zeros_like(long_vol),
        where=(long_vol > 0.0) & np.isfinite(long_vol),
    ) * active
    inverse_total = inverse.sum(axis=1, keepdims=True)
    allocation = np.divide(
        inverse,
        inverse_total,
        out=np.zeros_like(inverse),
        where=inverse_total > 0.0,
    )
    signed = np.sign(signal) * allocation
    signed *= np.where(signal < 0.0, float(params["short_scale"]), 1.0)

    portfolio_vol = np.sum(
        np.abs(signed) * np.where(np.isfinite(long_vol), long_vol, 0.0),
        axis=1,
    )
    target_scale = np.divide(
        float(params["target_vol"]),
        portfolio_vol,
        out=np.zeros(len(portfolio_vol)),
        where=portfolio_vol > 0.0,
    )
    target_scale = np.clip(target_scale, 0.0, 1.0)
    raw = signed * target_scale[:, None]

    vol_ratio = np.divide(
        fast_vol,
        long_vol,
        out=np.ones_like(fast_vol),
        where=(long_vol > 0.0) & np.isfinite(long_vol) & np.isfinite(fast_vol),
    )
    high_vol = np.nanmax(vol_ratio, axis=1) >= float(
        params["vol_ratio_trigger"]
    )
    raw[high_vol] *= float(params["high_vol_scale"])

    rebalance = market_utils.bars(int(params["rebalance_days"]))
    source = (np.arange(len(raw)) // rebalance) * rebalance
    held = raw[source]
    quantum = float(params["quantum"])
    held = np.round(held / quantum) * quantum
    held = np.clip(held, -1.0, 1.0)
    gross = np.abs(held).sum(axis=1)
    excessive = gross > 1.0
    held[excessive] /= gross[excessive, None]
    held[~np.isfinite(held)] = 0.0
    return held


def evaluate(
    market: dict[str, Any],
    weights: np.ndarray,
    folds: list[dict[str, str]],
    profile: dict[str, float],
    exact: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for fold_number, period in enumerate(folds, 1):
        metric = (
            engine.exact_backtest(market, weights, period, profile)
            if exact
            else engine.approximate_backtest(market, weights, period, profile)
        )
        rows.append({
            "fold": fold_number,
            "start": period["start"],
            "end": period["end"],
            **metric,
        })
    return engine.summarize(rows), rows


def flatten_approximate(row: dict[str, Any]) -> dict[str, Any]:
    output = dict(row)
    output["params"] = json.dumps(output["params"], sort_keys=True)
    output["failed_checks"] = json.dumps(output.get("failed_checks", []))
    return output


def parameter_plateau(
    passers: list[dict[str, Any]], config: dict[str, Any]
) -> dict[str, Any]:
    rules = config["plateau"]
    lookbacks = {
        tuple(item["params"]["lookbacks"])
        for item in passers
    }
    ema_pairs = {
        (
            item["params"]["ema_fast_days"],
            item["params"]["ema_slow_days"],
        )
        for item in passers
    }
    target_vols = {
        item["params"]["target_vol"]
        for item in passers
    }
    checks = {
        "minimum_passers": len(passers) >= int(rules["minimum_passers"]),
        "lookback_diversity": len(lookbacks) >= int(
            rules["minimum_lookback_sets"]
        ),
        "ema_diversity": len(ema_pairs) >= int(rules["minimum_ema_pairs"]),
        "target_vol_diversity": len(target_vols) >= int(
            rules["minimum_target_vols"]
        ),
    }
    return {
        "passes": all(checks.values()),
        "checks": checks,
        "passer_count": len(passers),
        "lookback_sets": sorted([list(item) for item in lookbacks]),
        "ema_pairs": sorted([list(item) for item in ema_pairs]),
        "target_vols": sorted(target_vols),
    }


def run_search(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    config = json.loads(manifest_path.read_text(encoding="utf-8"))
    market = market_utils.load_market(
        Path(config["dataset"]["dataset_root"]),
        config["symbols"],
    )
    candidates = enumerate_candidates(config)
    profiles = config["execution"]
    structural_cache: dict[str, np.ndarray] = {}
    vol_cache: dict[int, np.ndarray] = {}
    fast_vol = realized_vol(market["close"], 14)
    approximate_rows: list[dict[str, Any]] = []

    for candidate in candidates:
        key = structural_key(candidate)
        if key not in structural_cache:
            structural_cache[key] = structural_signal(market, candidate)
        vol_days = int(candidate["params"]["vol_days"])
        if vol_days not in vol_cache:
            vol_cache[vol_days] = realized_vol(market["close"], vol_days)
        weights = construct_weights(
            structural_cache[key],
            vol_cache[vol_days],
            fast_vol,
            candidate,
        )
        summary, _ = evaluate(
            market,
            weights,
            config["folds"],
            profiles["conservative"],
            exact=False,
        )
        checks = engine.gate_checks(
            summary,
            config["gates"]["conservative"],
        )
        approximate_rows.append({
            **candidate,
            **summary,
            "passes": all(checks.values()),
            "failed_checks": [
                name for name, passed in checks.items() if not passed
            ],
        })

    approximate_rows.sort(key=lambda item: item["score"], reverse=True)
    approximate_passers = [item for item in approximate_rows if item["passes"]]
    finalists = (approximate_passers or approximate_rows)[
        : int(config["search"]["top_exact"])
    ]
    candidate_map = {item["id"]: item for item in candidates}
    exact_rows: list[dict[str, Any]] = []
    exact_runs: list[dict[str, Any]] = []
    weight_cache: dict[str, np.ndarray] = {}

    for approximate in finalists:
        candidate = candidate_map[approximate["id"]]
        key = structural_key(candidate)
        vol_days = int(candidate["params"]["vol_days"])
        weights = construct_weights(
            structural_cache[key],
            vol_cache[vol_days],
            fast_vol,
            candidate,
        )
        weight_cache[candidate["id"]] = weights
        conservative, conservative_runs = evaluate(
            market,
            weights,
            config["folds"],
            profiles["conservative"],
            exact=True,
        )
        stress, stress_runs = evaluate(
            market,
            weights,
            config["folds"],
            profiles["stress"],
            exact=True,
        )
        conservative_checks = engine.gate_checks(
            conservative,
            config["gates"]["conservative"],
        )
        stress_checks = engine.gate_checks(
            stress,
            config["gates"]["stress"],
        )
        passes = all(conservative_checks.values()) and all(
            stress_checks.values()
        )
        exact_rows.append({
            **candidate,
            "conservative": conservative,
            "stress": stress,
            "passes": passes,
            "combined_score": conservative["score"] + 0.5 * stress["score"],
            "failed_conservative": [
                name
                for name, passed in conservative_checks.items()
                if not passed
            ],
            "failed_stress": [
                name for name, passed in stress_checks.items() if not passed
            ],
        })
        exact_runs.extend({
            "candidate_id": candidate["id"],
            "profile": "conservative",
            **row,
        } for row in conservative_runs)
        exact_runs.extend({
            "candidate_id": candidate["id"],
            "profile": "stress",
            **row,
        } for row in stress_runs)

    exact_rows.sort(key=lambda item: item["combined_score"], reverse=True)
    passers = [item for item in exact_rows if item["passes"]]
    ranked = passers or exact_rows
    plateau = parameter_plateau(passers, config)

    components = ranked[: int(config["search"]["ensemble_size"])]
    ensemble_weights = np.median(
        np.stack([weight_cache[item["id"]] for item in components], axis=2),
        axis=2,
    )
    gross = np.abs(ensemble_weights).sum(axis=1)
    excessive = gross > 1.0
    ensemble_weights[excessive] /= gross[excessive, None]
    ensemble_conservative, ensemble_conservative_runs = evaluate(
        market,
        ensemble_weights,
        config["folds"],
        profiles["conservative"],
        exact=True,
    )
    ensemble_stress, ensemble_stress_runs = evaluate(
        market,
        ensemble_weights,
        config["folds"],
        profiles["stress"],
        exact=True,
    )
    ensemble_conservative_checks = engine.gate_checks(
        ensemble_conservative,
        config["gates"]["conservative"],
    )
    ensemble_stress_checks = engine.gate_checks(
        ensemble_stress,
        config["gates"]["stress"],
    )
    ensemble_passes = all(ensemble_conservative_checks.values()) and all(
        ensemble_stress_checks.values()
    )
    ensemble_score = ensemble_conservative["score"] + 0.5 * ensemble_stress["score"]
    best = ranked[0]

    if ensemble_passes and ensemble_score >= best["combined_score"]:
        selected = {
            "type": "median_ensemble",
            "components": [
                {
                    "id": item["id"],
                    "params": item["params"],
                }
                for item in components
            ],
            "conservative": ensemble_conservative,
            "stress": ensemble_stress,
            "conservative_checks": ensemble_conservative_checks,
            "stress_checks": ensemble_stress_checks,
            "combined_score": ensemble_score,
        }
        selected_runs = [
            *(
                {"profile": "conservative", **row}
                for row in ensemble_conservative_runs
            ),
            *(
                {"profile": "stress", **row}
                for row in ensemble_stress_runs
            ),
        ]
        selected_passes = True
    else:
        selected = {
            "type": "single",
            "id": best["id"],
            "params": best["params"],
            "conservative": best["conservative"],
            "stress": best["stress"],
            "conservative_checks": engine.gate_checks(
                best["conservative"],
                config["gates"]["conservative"],
            ),
            "stress_checks": engine.gate_checks(
                best["stress"],
                config["gates"]["stress"],
            ),
            "combined_score": best["combined_score"],
        }
        selected_runs = [
            row
            for row in exact_runs
            if row["candidate_id"] == best["id"]
        ]
        selected_passes = best["passes"]

    qualifies = bool(selected_passes and plateau["passes"])
    report = {
        "experiment_id": config["experiment_id"],
        "dataset_archive_sha256": config["dataset"]["archive_sha256"],
        "limitations": [
            "All available history has informed model development; historical results are cross-validation evidence, not pristine out-of-sample proof.",
            "Short exposure is simulated from Spot OHLCV with explicit carry stress; actual perpetual funding, margin, liquidation and order-book execution require separate validation.",
            "A passing result authorizes only prospective paper-forward evaluation with frozen parameters."
        ],
        "summary": {
            "candidate_count": len(candidates),
            "approximate_conservative_passers": len(approximate_passers),
            "exact_evaluated": len(exact_rows),
            "exact_dual_profile_passers": len(passers),
            "parameter_plateau": plateau,
            "qualifies_for_derivatives_validation_and_prospective_paper_forward": qualifies,
            "automatic_paper_forward_started": False,
            "live_trading_enabled": False,
        },
        "selected_strategy": selected,
        "selected_runs": selected_runs,
        "decision": (
            "eligible_for_derivatives_validation_and_prospective_paper_forward"
            if qualifies
            else "continue_research_no_promotion"
        ),
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "consensus_search_v5.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "selected_consensus_strategy.json").write_text(
        json.dumps(selected, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame([
        flatten_approximate(item)
        for item in approximate_rows[:1000]
    ]).to_csv(output_root / "top_approximate_candidates.csv", index=False)
    exact_flat: list[dict[str, Any]] = []
    for item in exact_rows:
        exact_flat.append({
            "id": item["id"],
            "params": json.dumps(item["params"], sort_keys=True),
            "passes": item["passes"],
            "combined_score": item["combined_score"],
            **{
                f"conservative_{key}": value
                for key, value in item["conservative"].items()
            },
            **{
                f"stress_{key}": value
                for key, value in item["stress"].items()
            },
            "failed_conservative": json.dumps(
                item["failed_conservative"]
            ),
            "failed_stress": json.dumps(item["failed_stress"]),
        })
    pd.DataFrame(exact_flat).to_csv(
        output_root / "exact_candidates.csv",
        index=False,
    )
    pd.DataFrame(exact_runs).to_csv(
        output_root / "exact_fold_runs.csv",
        index=False,
    )
    pd.DataFrame(selected_runs).to_csv(
        output_root / "selected_fold_runs.csv",
        index=False,
    )
    shutil.copy2(manifest_path, output_root / manifest_path.name)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/bybit_consensus_search_v5.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/bybit_consensus_search_v5"),
    )
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    report = run_search(args.manifest, args.output)
    print(json.dumps(report["summary"], sort_keys=True))
    qualified = report["summary"][
        "qualifies_for_derivatives_validation_and_prospective_paper_forward"
    ]
    return 1 if args.require_qualified and not qualified else 0


if __name__ == "__main__":
    raise SystemExit(main())
