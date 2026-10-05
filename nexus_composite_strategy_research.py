"""Autonomous, artifact-bound *exploratory* composite strategy search.

Uses only the existing independently validated, immutable Bybit replay archive.
Its historical years have already informed NEXUS development: these folds are
diagnostic, NEVER a new pristine holdout or Paper-promotion authority.

There is NO arbitrary trade/position lifetime count limit in this engine. A
single long/flat position per symbol is the explicit, collateral-backed netting
model; funding, L2, short trades, and concurrent independent Paper tranches are
not simulated or claimed. Never connect this engine to an owner Paper profile.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from nexus_demo_archive_replay import ARCHIVE_SHA256
from nexus_mechanism_factory import (
    MechanismFactoryError,
    factory_configs,
    factory_ids,
    factory_peer_ids,
    factory_signal,
    generate_factory_contracts,
    generate_factory_contracts_v3,
    load_factory_contract,
)
from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame

SCHEMA = "nexus.automatic-composite-research.v1"
LEDGER_SCHEMA = "nexus.automatic-composite-novelty-ledger.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MECHANISMS = (
    "structural_pullback",
    "volatility_compression_expansion",
    "bar_proxy_vwap_reclaim",
    "failed_range_break_reversal",
    "cross_pair_relative_reclaim",
    "lagged_peer_impulse_confirmation",
    "peer_shock_noncontagion_rebound",
    "relative_momentum_reacceleration",
    "lagged_peer_volatility_release",
    "cross_pair_volatility_catchup",
    "regime_conditional_composite",
)
# The historical sequential frontier above is immutable.  Once it is exhausted,
# do NOT fall back to risk-parameter cycling.  Screen a new reviewed generation
# in one bounded tournament, then spend the expensive full replay + independent
# QA on only the strongest training-screen candidate.
FRONTIER_GENERATION1 = (
    "multi_horizon_trend_reacceleration",
    "trend_vwap_pullback_reclaim",
    "volume_dryup_breakout",
    "range_midpoint_reclaim",
    "downside_exhaustion_rebound",
    "volatility_contraction_trend_reentry",
    "volatility_expansion_pullback_reclaim",
    "relative_strength_persistence_breakout",
    "relative_weakness_exhaustion_rebound",
    "volatility_leadership_reversal",
)
# Generation 2 is intentionally topology-diverse and uses only already verified
# closed Spot inputs.  These are new causal hypotheses, never parameter sweeps.
FRONTIER_GENERATION2 = (
    "trend_efficiency_breakout",
    "serial_dependence_breakout",
    "range_wick_absorption_rebound",
    "volatility_of_volatility_release",
    "peer_beta_residual_reclaim",
    "prior_day_breakout_continuation",
)
FIXED_FACTORY_SPECS = load_factory_contract()
GENERATED_FACTORY_SPECS_V2 = generate_factory_contracts(FIXED_FACTORY_SPECS, limit=24)
GENERATED_FACTORY_SPECS_V3 = generate_factory_contracts_v3(
    {**FIXED_FACTORY_SPECS, **GENERATED_FACTORY_SPECS_V2}, limit=36
)
GENERATED_FACTORY_SPECS = {
    **GENERATED_FACTORY_SPECS_V2,
    **GENERATED_FACTORY_SPECS_V3,
}
FACTORY_SPECS = {**FIXED_FACTORY_SPECS, **GENERATED_FACTORY_SPECS}
FIXED_FACTORY_MECHANISMS = factory_ids(FIXED_FACTORY_SPECS)
GENERATED_FACTORY_MECHANISMS = factory_ids(GENERATED_FACTORY_SPECS)
FACTORY_MECHANISMS = factory_ids(FACTORY_SPECS)
FRONTIER_MECHANISMS = FRONTIER_GENERATION1 + FRONTIER_GENERATION2 + FACTORY_MECHANISMS
ALL_MECHANISMS = MECHANISMS + FRONTIER_MECHANISMS
PEER_MECHANISMS = frozenset({
    "cross_pair_relative_reclaim",
    "lagged_peer_impulse_confirmation",
    "peer_shock_noncontagion_rebound",
    "relative_momentum_reacceleration",
    "lagged_peer_volatility_release",
    "cross_pair_volatility_catchup",
    "relative_strength_persistence_breakout",
    "relative_weakness_exhaustion_rebound",
    "volatility_leadership_reversal",
    "peer_beta_residual_reclaim",
}) | factory_peer_ids(FACTORY_SPECS)
FRONTIER_SCREEN_VERSION = "nexus.frontier-train-screen.v5"
FRONTIER_SHORTLIST_SIZE = 3
GENERATED_FRONTIER_BATCH_SIZE = 12
# Distinct entry mechanisms vs risk/feature parameter variations are explicitly
# separately labeled; risk variants do NOT count as independent new edges.
CONFIGS = tuple(
    {"mechanism": mechanism, "risk_variant": v, "entry_model": "closed_4h_1h_15m_next_open"}
    for mechanism in MECHANISMS for v in (0, 1)
)
FRONTIER_CONFIGS = tuple(
    {"mechanism": mechanism, "risk_variant": 0, "entry_model": "closed_4h_1h_15m_next_open"}
    for mechanism in (FRONTIER_GENERATION1 + FRONTIER_GENERATION2)
) + factory_configs(FACTORY_SPECS)
MIN_BARS_15M = 960
TRAIN_FRAC, VALID_FRAC = .60, .20
# Each experiment has its own 10,000 USDT cash. Never use the 500 USDT owner wallet.
SIM_CASH = 10_000.0
ENTRY_FEE_BPS, ENTRY_SLIP_BPS = 10.0, 5.0
STRESS_FEE_BPS, STRESS_SLIP_BPS = 25.0, 15.0


class CompositeResearchError(ValueError):
    pass


def digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode("utf-8")).hexdigest()


def safe_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def _closed_asof(source: pd.DataFrame, interval_ms: int, decision: pd.DataFrame,
                 fields: dict[str, pd.Series], label: str) -> pd.DataFrame:
    """No 4h or 1h candle is visible until its actual UTC close timestamp."""
    frame = pd.DataFrame({"available_at": pd.to_datetime(source["timestamp"], utc=True)
                         + pd.to_timedelta(interval_ms, unit="ms")})
    for key, series in fields.items():
        frame[label + key] = series.to_numpy()
    if not frame["available_at"].is_monotonic_increasing or frame["available_at"].duplicated().any():
        raise CompositeResearchError("higher timeframe close timestamps corrupt")
    joined = pd.merge_asof(decision[["decision_at"]].sort_values("decision_at"),
                           frame, left_on="decision_at", right_on="available_at",
                           direction="backward", allow_exact_matches=True)
    valid = joined["available_at"].notna()
    if (joined.loc[valid, "available_at"] > joined.loc[valid, "decision_at"]).any():
        raise CompositeResearchError("look-ahead as-of violation")
    return joined.drop(columns=["decision_at", "available_at"])


def build_features(frames: dict[str, pd.DataFrame], *, peer_15m: pd.DataFrame | None = None) -> pd.DataFrame:
    """Derive observable structural/volatility/bar-proxy features from CLOSED bars."""
    try:
        f = frames["minute15"].reset_index(drop=True).copy()
        h = frames["hour1"].reset_index(drop=True)
        q = frames["hour4"].reset_index(drop=True)
    except KeyError as exc:
        raise CompositeResearchError("one required historical timeframe is missing") from exc
    if len(f) < MIN_BARS_15M:
        raise CompositeResearchError("insufficient 15m history for bounded composite research")
    for tf, df, ms in (("minute15", f, 900_000), ("hour1", h, 3_600_000),
                       ("hour4", q, 14_400_000)):
        t = pd.to_datetime(df["timestamp"], utc=True, errors="raise")
        if t.duplicated().any() or not t.is_monotonic_increasing or not (t.diff().dropna()
                    == pd.to_timedelta(ms, unit="ms")).all():
            raise CompositeResearchError(tf + " chronology is not a complete UTC grid")
        numeric = df[["open", "high", "low", "close", "volume"]].astype(float)
        if (not np.isfinite(numeric.to_numpy()).all()
                or (numeric[["open", "high", "low", "close"]] <= 0).any().any()
                or (numeric["volume"] < 0).any().any()
                or (numeric["high"] < numeric[["open", "close", "low"]].max(axis=1)).any()
                or (numeric["low"] > numeric[["open", "close", "high"]].min(axis=1)).any()):
            raise CompositeResearchError(tf + " OHLCV failed strict validation")
    f["decision_at"] = pd.to_datetime(f["timestamp"], utc=True) + pd.Timedelta(minutes=15)
    higher4 = _closed_asof(q, 14_400_000, f, {
        "up": ((q["close"].astype(float) > q["close"].shift(1).rolling(12).median())
                & (q["low"].astype(float) > q["low"].shift(4).rolling(8).min())).astype(float),
        "range": ((q["close"].astype(float) <= q["high"].shift(1).rolling(12).max())
                  & (q["close"].astype(float) >= q["low"].shift(1).rolling(12).min())).astype(float),
    }, "h4_")
    hourly_range = (h["high"].astype(float) - h["low"].astype(float)) / h["close"].astype(float)
    higher1 = _closed_asof(h, 3_600_000, f, {
        "compression": (hourly_range.rolling(6, min_periods=6).mean()
                        < hourly_range.shift(1).rolling(48, min_periods=48).median() * .8).astype(float),
        "vol_ok": (hourly_range < hourly_range.shift(1).rolling(72, min_periods=72).median() * 1.65).astype(float),
    }, "h1_")
    for c in higher4.columns:
        f[c] = higher4[c].to_numpy()
    for c in higher1.columns:
        f[c] = higher1[c].to_numpy()
    close = f["close"].astype(float)
    volume = f["volume"].astype(float)
    typical = (f["high"] + f["low"] + close) / 3.0
    # Candle-volume proxy, NOT authenticated trade-by-trade VWAP.
    utc_day = f["decision_at"].dt.floor("D")
    weighted = (typical * volume).groupby(utc_day).cumsum()
    cum_volume = volume.groupby(utc_day).cumsum().replace(0.0, np.nan)
    f["bar_proxy_vwap"] = weighted / cum_volume
    f["prior_hi"] = f["high"].shift(1).rolling(18, min_periods=18).max()
    f["prior_lo"] = f["low"].shift(1).rolling(18, min_periods=18).min()
    f["prior_range_mid"] = (f["prior_hi"] + f["prior_lo"]) / 2.0
    f["prior_range_width_pct"] = (
        (f["prior_hi"] - f["prior_lo"]) / close.shift(1).replace(0.0, np.nan)
    )
    f["rel_vol"] = volume / volume.shift(1).rolling(20, min_periods=20).mean().replace(0, np.nan)
    f["rel_vol_previous"] = f["rel_vol"].shift(1)
    f["atr"] = (f["high"] - f["low"]).shift(1).rolling(14, min_periods=14).mean()
    own_return_1h = close.pct_change(4)
    own_return_4h = close.pct_change(16)
    f["lagged_own_return_1h"] = own_return_1h.shift(1)
    f["lagged_own_return_4h"] = own_return_4h.shift(1)
    f["own_return_1h_abs_baseline"] = (
        own_return_1h.shift(2).abs().rolling(96, min_periods=96).median()
    )
    own_realized = close.pct_change().shift(1).rolling(16, min_periods=16).std()
    f["own_realized_volatility"] = own_realized
    f["own_realized_volatility_baseline"] = (
        own_realized.shift(1).rolling(96, min_periods=96).median()
    )
    bar_range = (f["high"].astype(float) - f["low"].astype(float)).replace(0.0, np.nan)
    f["close_location"] = (close - f["low"].astype(float)) / bar_range
    f["body_efficiency"] = (close - f["open"].astype(float)).abs() / bar_range

    # Generation-2 features are strictly causal.  Every regime statistic ends
    # at least one completed 15m bar before the decision bar; current-bar OHLCV
    # is used only for the explicit closed-bar confirmation in signal_for().
    one_bar_return = close.pct_change()
    path_length_16 = one_bar_return.abs().shift(1).rolling(16, min_periods=16).sum()
    displacement_16 = (close.shift(1) / close.shift(17) - 1.0)
    f["trend_efficiency_16"] = (
        displacement_16.abs() / path_length_16.replace(0.0, np.nan)
    ).replace([np.inf, -np.inf], np.nan)
    f["trend_direction_16"] = displacement_16
    f["lagged_return_serial_corr"] = (
        one_bar_return.shift(1).rolling(48, min_periods=48).corr(one_bar_return.shift(2))
    )

    # Generator-v3 distribution/path-state primitives.  Every statistic ends
    # at i-1 or earlier; the current closed decision bar cannot alter context.
    lagged_return = one_bar_return.shift(1)
    f["lagged_return_skew_64"] = lagged_return.rolling(64, min_periods=64).skew()
    downside_sq = lagged_return.clip(upper=0.0).pow(2).rolling(64, min_periods=64).sum()
    total_sq = lagged_return.pow(2).rolling(64, min_periods=64).sum().replace(0.0, np.nan)
    f["lagged_downside_variance_share_64"] = (
        downside_sq / total_sq
    ).replace([np.inf, -np.inf], np.nan)

    previous_close = close.shift(1)
    rolling_high_32 = previous_close.rolling(32, min_periods=32).max()
    rolling_low_32 = previous_close.rolling(32, min_periods=32).min()
    f["lagged_drawdown_depth_32"] = (
        previous_close / rolling_high_32.replace(0.0, np.nan) - 1.0
    ).replace([np.inf, -np.inf], np.nan)
    f["lagged_recovery_from_low_32"] = (
        previous_close / rolling_low_32.replace(0.0, np.nan) - 1.0
    ).replace([np.inf, -np.inf], np.nan)

    abs_return = one_bar_return.abs()
    f["lagged_abs_return_autocorr_48"] = (
        abs_return.shift(1).rolling(48, min_periods=48).corr(abs_return.shift(2))
    )
    f["lagged_close_location_persistence_16"] = (
        f["close_location"].shift(1).rolling(16, min_periods=16).mean()
    )

    lower_wick = (
        np.minimum(f["open"].astype(float), close) - f["low"].astype(float)
    ) / bar_range
    f["lagged_lower_wick_absorption"] = (
        lower_wick.shift(1).rolling(8, min_periods=8).mean()
    )
    f["lower_wick_absorption_baseline"] = (
        lower_wick.shift(9).rolling(96, min_periods=96).median()
    )
    upper_wick = (
        f["high"].astype(float) - np.maximum(f["open"].astype(float), close)
    ) / bar_range
    lower_wick_mean = lower_wick.shift(1).rolling(32, min_periods=32).mean()
    upper_wick_mean = upper_wick.shift(1).rolling(32, min_periods=32).mean()
    f["lagged_wick_asymmetry_32"] = (
        lower_wick_mean / upper_wick_mean.replace(0.0, np.nan)
    ).replace([np.inf, -np.inf], np.nan)

    own_vol_of_vol = own_realized.shift(1).rolling(32, min_periods=32).std()
    f["own_volatility_of_volatility"] = own_vol_of_vol
    f["own_volatility_of_volatility_baseline"] = (
        own_vol_of_vol.shift(1).rolling(96, min_periods=96).median()
    )

    # Previous FULL UTC-day anchors only.  A partial edge day cannot define a
    # prior-day level, and today's bars never alter today's mapped anchor.
    bar_day = pd.to_datetime(f["timestamp"], utc=True).dt.floor("D")
    daily = pd.DataFrame({
        "day": bar_day,
        "high": f["high"].astype(float),
        "low": f["low"].astype(float),
        "close": close,
    }).groupby("day", sort=True).agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last"),
        count=("close", "size"),
    )
    prior_daily = daily.shift(1)
    complete_prior = prior_daily["count"] == 96
    prior_daily.loc[~complete_prior, ["high", "low", "close"]] = np.nan
    f["prior_day_high"] = bar_day.map(prior_daily["high"])
    f["prior_day_low"] = bar_day.map(prior_daily["low"])
    f["prior_day_close"] = bar_day.map(prior_daily["close"])

    if peer_15m is not None:
        # New causal feature, derived exclusively from two independently
        # verified, exactly time-aligned CLOSED 15m Spot candle grids.
        # A peer candle may not be borrowed from a later/asynchronous bar.
        peer = peer_15m.reset_index(drop=True)
        peer_times = pd.to_datetime(peer["timestamp"], utc=True, errors="raise")
        own_times = pd.to_datetime(f["timestamp"], utc=True)
        if (
            len(peer) != len(f)
            or peer_times.duplicated().any()
            or not peer_times.is_monotonic_increasing
            or not peer_times.equals(own_times)
            or not (peer_times.diff().dropna() == pd.Timedelta(minutes=15)).all()
        ):
            raise CompositeResearchError("cross-pair Spot candles are not the exact same closed UTC grid")
        peer_ohlcv = peer[["open", "high", "low", "close", "volume"]].astype(float)
        if (
            not np.isfinite(peer_ohlcv.to_numpy()).all()
            or (peer_ohlcv[["open", "high", "low", "close"]] <= 0).any().any()
            or (peer_ohlcv["volume"] < 0).any()
            or (peer_ohlcv["high"] < peer_ohlcv[["open", "close", "low"]].max(axis=1)).any()
            or (peer_ohlcv["low"] > peer_ohlcv[["open", "close", "high"]].min(axis=1)).any()
        ):
            raise CompositeResearchError("cross-pair Spot candle OHLCV integrity failed")
        relative = np.log(close / peer_ohlcv["close"])
        # Mean/std are based on bars completed strictly BEFORE the current
        # decision candle; current relative close is only visible at its close.
        baseline = relative.shift(1).rolling(96, min_periods=96)
        scale = baseline.std().replace(0.0, np.nan)
        score = (relative - baseline.mean()) / scale
        f["cross_pair_relative_z"] = score.replace([np.inf, -np.inf], np.nan)
        f["cross_pair_relative_z_previous"] = f["cross_pair_relative_z"].shift(1)
        # Different cross-asset hypothesis: the peer impulse was complete
        # one entire 15m candle ago. Use only earlier peer bars to establish
        # its ordinary amplitude, so the observed shock cannot set its gate.
        peer_hour_return = peer_ohlcv["close"].pct_change(4)
        f["lagged_peer_impulse"] = peer_hour_return.shift(1)
        f["lagged_peer_impulse_baseline"] = (
            peer_hour_return.shift(2).abs().rolling(96, min_periods=96).median()
        )
        f["lagged_own_response"] = close.pct_change(4).shift(1)
        # Materially distinct peer-relative momentum continuation, not peer shock
        # contagion or relative-price mean reversion. Both same-grid 15m bars
        # are closed at this decision; baseline ends two bars earlier.
        relative_momentum = close.pct_change(4) - peer_ohlcv["close"].pct_change(4)
        f["relative_momentum"] = relative_momentum
        f["relative_momentum_previous"] = relative_momentum.shift(1)
        f["relative_momentum_baseline"] = (
            relative_momentum.shift(2).rolling(96, min_periods=96).median()
        )
        # Persistent cross-asset volatility dispersion, not a discrete peer
        # shock. All realized-volatility inputs end at least one full 15m
        # candle before the current decision; the current peer bar cannot
        # influence the own-asset breakout decision.
        own_return = close.pct_change()
        peer_return = peer_ohlcv["close"].pct_change()
        own_realized = own_return.shift(1).rolling(16, min_periods=16).std()
        peer_realized = peer_return.shift(1).rolling(16, min_periods=16).std()
        vol_ratio = own_realized / peer_realized.replace(0.0, np.nan)
        f["cross_pair_volatility_ratio"] = vol_ratio.replace([np.inf, -np.inf], np.nan)
        f["cross_pair_volatility_ratio_baseline"] = (
            vol_ratio.shift(1).rolling(96, min_periods=96).median()
        )
        f["peer_realized_volatility"] = peer_realized
        f["peer_realized_volatility_baseline"] = (
            peer_realized.shift(1).rolling(96, min_periods=96).median()
        )

        # Rolling peer beta is estimated strictly from returns ending at i-2.
        # The i-1 residual is then observed as a lagged dislocation; neither the
        # current own nor current peer return participates in beta estimation.
        own_hist = own_return.shift(2)
        peer_hist = peer_return.shift(2)
        peer_var = peer_hist.rolling(96, min_periods=96).var().replace(0.0, np.nan)
        peer_beta = own_hist.rolling(96, min_periods=96).cov(peer_hist) / peer_var
        lagged_residual = own_return.shift(1) - peer_beta * peer_return.shift(1)
        residual_history = own_hist - peer_beta.shift(1) * peer_hist
        f["peer_beta_lagged"] = peer_beta.replace([np.inf, -np.inf], np.nan)
        f["lagged_peer_beta_residual"] = lagged_residual.replace([np.inf, -np.inf], np.nan)
        f["peer_beta_residual_scale"] = (
            residual_history.rolling(96, min_periods=96).std().replace(0.0, np.nan)
        )

        # Generator-v3 peer lead/lag relation.  At decision bar i, the newest
        # estimated pair is own(i-2) versus peer(i-3), so peer leadership is
        # learned only from history that was already complete before i-1.
        f["lagged_peer_lead_corr_96"] = (
            own_return.shift(2).rolling(96, min_periods=96).corr(peer_return.shift(3))
        )
    return f


def signal_for(frame: pd.DataFrame, config: dict[str, Any]) -> np.ndarray:
    mechanism = config["mechanism"]
    if mechanism not in ALL_MECHANISMS or config["risk_variant"] not in (0, 1):
        raise CompositeResearchError("unreviewed strategy grammar")
    if mechanism in FACTORY_SPECS:
        if config["risk_variant"] != 0:
            raise CompositeResearchError("factory mechanisms have one fixed risk contract")
        try:
            signal = factory_signal(
                frame,
                mechanism,
                specs=FACTORY_SPECS,
                expected_contract_digest=config.get("factory_contract_digest"),
            )
        except MechanismFactoryError as exc:
            raise CompositeResearchError("factory mechanism contract invalid") from exc
        atr_ok = frame["atr"].notna() & np.isfinite(frame["atr"]) & (frame["atr"] > 0)
        return (pd.Series(signal, index=frame.index) & atr_ok).fillna(False).to_numpy(dtype=bool)
    c, lo, o = frame["close"], frame["low"], frame["open"]
    ok = frame[["h4_up", "h4_range", "h1_compression", "h1_vol_ok", "rel_vol",
                "prior_hi", "prior_lo", "atr"]].notna().all(axis=1) & (frame["atr"] > 0)
    if mechanism == "structural_pullback":
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (lo <= frame["prior_hi"]) & (
            c > frame["prior_hi"]) & (c > o) & (frame["rel_vol"] > .85)
    elif mechanism == "volatility_compression_expansion":
        s = (frame["h1_compression"] == 1) & (c > frame["prior_hi"]) & (
            frame["rel_vol"] >= 1.20) & (c > o)
    elif mechanism == "bar_proxy_vwap_reclaim":
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            c.shift(1) < frame["bar_proxy_vwap"].shift(1)) & (
            c > frame["bar_proxy_vwap"]) & (frame["rel_vol"] >= .9)
    elif mechanism == "lagged_peer_impulse_confirmation":
        required = {"lagged_peer_impulse", "lagged_peer_impulse_baseline",
                    "lagged_own_response"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("peer impulse requires exact verified aligned peer history")
        shock = frame["lagged_peer_impulse"]
        benchmark = frame["lagged_peer_impulse_baseline"]
        lagged = frame["lagged_own_response"]
        # Not a hedge or relative-z mean reversion: a peer leads one entire
        # closed candle, target asset has not caught up, and its own range
        # breakout confirms only at THIS close. Fill is at NEXT open.
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            shock > .003) & (shock > benchmark * 1.25) & (
            lagged > -.01) & (lagged < shock * .65) & (
            c > frame["prior_hi"]) & (c > o) & (frame["rel_vol"] > 1.05) & (
            np.isfinite(shock) & np.isfinite(benchmark) & np.isfinite(lagged))
    elif mechanism == "peer_shock_noncontagion_rebound":
        required = {"lagged_peer_impulse", "lagged_peer_impulse_baseline",
                    "lagged_own_response"}
        if not required <= set(frame.columns):
            raise CompositeResearchError(
                "peer noncontagion requires exact verified aligned peer history"
            )
        shock = frame["lagged_peer_impulse"]
        baseline = frame["lagged_peer_impulse_baseline"]
        own_before = frame["lagged_own_response"]
        # Distinct from positive peer leadership and single-symbol range failure:
        # the previous closed negative peer shock did not spread proportionally
        # to the own asset; THIS closed own bar rejects a local range break.
        # Execution remains NEXT own 15m open; no current peer bar is read.
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            shock < -.004) & (-shock > baseline * 1.30) & (
            own_before > shock * .50) & (own_before < .006) & (
            lo < frame["prior_lo"]) & (c > frame["prior_lo"]) & (
            c > o) & (frame["rel_vol"] >= 1.10) & (
            np.isfinite(shock) & np.isfinite(baseline) & np.isfinite(own_before))
    elif mechanism == "relative_momentum_reacceleration":
        required = {"relative_momentum", "relative_momentum_previous",
                    "relative_momentum_baseline"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("relative momentum requires exact verified aligned peer history")
        rel = frame["relative_momentum"]
        previous = frame["relative_momentum_previous"]
        baseline = frame["relative_momentum_baseline"]
        # Target leads peer, decelerates briefly, then visibly re-accelerates
        # at THIS close during completed higher-timeframe trend confirmation.
        # Only NEXT own 15m open can fill; no fabricated spread/peer short.
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            previous > baseline) & (previous > .0015) & (
            rel > previous + .0010) & (rel > .0030) & (
            c > frame["prior_hi"]) & (c > o) & (frame["rel_vol"] >= 1.0) & (
            np.isfinite(rel) & np.isfinite(previous) & np.isfinite(baseline))
    elif mechanism == "lagged_peer_volatility_release":
        required = {"lagged_peer_impulse", "lagged_peer_impulse_baseline",
                    "lagged_own_response"}
        if not required <= set(frame.columns):
            raise CompositeResearchError(
                "peer volatility release requires exact verified aligned peer history"
            )
        shock_abs = frame["lagged_peer_impulse"].abs()
        baseline = frame["lagged_peer_impulse_baseline"]
        own_abs = frame["lagged_own_response"].abs()
        # Direction-agnostic cross-asset volatility transmission: the peer had
        # an unusually large move one entire closed 15m candle ago while the
        # own asset remained muted. Only a later OWN upside range expansion in
        # a completed compression/range context may trigger a long at NEXT open.
        # This is neither peer-direction following nor a paired/spread trade.
        s = (frame["h4_range"] == 1) & (frame["h1_compression"] == 1) & (
            frame["h1_vol_ok"] == 1) & (shock_abs > .006) & (
            shock_abs > baseline * 1.50) & (own_abs < shock_abs * .35) & (
            own_abs < .0045) & (c > frame["prior_hi"]) & (c > o) & (
            frame["rel_vol"] >= 1.15) & (
            np.isfinite(shock_abs) & np.isfinite(baseline) & np.isfinite(own_abs))
    elif mechanism == "cross_pair_volatility_catchup":
        required = {"cross_pair_volatility_ratio",
                    "cross_pair_volatility_ratio_baseline",
                    "peer_realized_volatility",
                    "peer_realized_volatility_baseline"}
        if not required <= set(frame.columns):
            raise CompositeResearchError(
                "cross-pair volatility catch-up requires exact verified aligned peer history"
            )
        ratio = frame["cross_pair_volatility_ratio"]
        ratio_baseline = frame["cross_pair_volatility_ratio_baseline"]
        peer_rv = frame["peer_realized_volatility"]
        peer_rv_baseline = frame["peer_realized_volatility_baseline"]
        # Persistent 4h realized-volatility under-participation versus the peer,
        # rather than a one-candle peer shock. Entry is permitted only after
        # THIS own closed bar confirms upside range expansion; execution remains
        # NEXT own 15m open. No peer direction, hedge, L2, or flow is inferred.
        s = ((frame["h4_range"] == 1) | (frame["h4_up"] == 1)) & (
            frame["h1_vol_ok"] == 1) & (ratio < .65) & (
            ratio < ratio_baseline * .75) & (peer_rv > peer_rv_baseline * 1.10) & (
            c > frame["prior_hi"]) & (c > o) & (frame["rel_vol"] >= 1.05) & (
            np.isfinite(ratio) & np.isfinite(ratio_baseline)
            & np.isfinite(peer_rv) & np.isfinite(peer_rv_baseline))
    elif mechanism == "multi_horizon_trend_reacceleration":
        required = {"lagged_own_return_1h", "lagged_own_return_4h", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("multi-horizon trend mechanism lacks causal own-return features")
        r1 = frame["lagged_own_return_1h"]
        r4 = frame["lagged_own_return_4h"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            r4 > .004) & (r1 > .001) & (c > frame["prior_hi"]) & (
            c > o) & (frame["close_location"] >= .70) & (frame["rel_vol"] >= 1.0) & (
            np.isfinite(r1) & np.isfinite(r4))
    elif mechanism == "trend_vwap_pullback_reclaim":
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            c.shift(1) < frame["bar_proxy_vwap"].shift(1)) & (
            c > frame["bar_proxy_vwap"]) & (c > frame["prior_range_mid"]) & (
            c > o) & (frame["rel_vol"] >= .90)
    elif mechanism == "volume_dryup_breakout":
        s = ((frame["h4_up"] == 1) | (frame["h4_range"] == 1)) & (
            frame["h1_vol_ok"] == 1) & (frame["rel_vol_previous"] < .65) & (
            frame["rel_vol"] >= 1.30) & (c > frame["prior_hi"]) & (c > o) & (
            frame["body_efficiency"] >= .55) & (frame["close_location"] >= .70)
    elif mechanism == "range_midpoint_reclaim":
        mid = frame["prior_range_mid"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            c.shift(1) < mid.shift(1)) & (lo <= mid) & (c > mid) & (c > o) & (
            frame["close_location"] >= .65) & (frame["rel_vol"] >= .85)
    elif mechanism == "downside_exhaustion_rebound":
        required = {"lagged_own_return_1h", "own_return_1h_abs_baseline"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("downside-exhaustion mechanism lacks causal own-return history")
        r1 = frame["lagged_own_return_1h"]
        baseline = frame["own_return_1h_abs_baseline"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            r1 < -.004) & (r1.abs() > baseline * 1.30) & (
            lo < frame["prior_lo"]) & (c > frame["prior_lo"]) & (c > o) & (
            frame["close_location"] >= .65) & (frame["rel_vol"] >= 1.0) & (
            np.isfinite(r1) & np.isfinite(baseline))
    elif mechanism == "volatility_contraction_trend_reentry":
        rv = frame["own_realized_volatility"]
        rv_base = frame["own_realized_volatility_baseline"]
        s = (frame["h4_up"] == 1) & (frame["h1_compression"] == 1) & (
            frame["h1_vol_ok"] == 1) & (rv < rv_base * .75) & (
            c.shift(1) <= frame["bar_proxy_vwap"].shift(1)) & (
            c > frame["bar_proxy_vwap"]) & (c > o) & (frame["rel_vol"] >= .90) & (
            np.isfinite(rv) & np.isfinite(rv_base))
    elif mechanism == "volatility_expansion_pullback_reclaim":
        rv = frame["own_realized_volatility"]
        rv_base = frame["own_realized_volatility_baseline"]
        r1 = frame["lagged_own_return_1h"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            rv > rv_base * 1.35) & (r1 > .001) & (
            lo <= frame["prior_range_mid"]) & (c > frame["prior_range_mid"]) & (
            c > o) & (frame["close_location"] >= .60) & (frame["rel_vol"] >= 1.0) & (
            np.isfinite(rv) & np.isfinite(rv_base) & np.isfinite(r1))
    elif mechanism == "relative_strength_persistence_breakout":
        required = {"relative_momentum_previous", "relative_momentum_baseline",
                    "lagged_own_return_1h"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("relative-strength persistence requires aligned peer history")
        previous = frame["relative_momentum_previous"]
        baseline = frame["relative_momentum_baseline"]
        own_r1 = frame["lagged_own_return_1h"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            previous > .002) & (previous > baseline) & (own_r1 > 0.0) & (
            c > frame["prior_hi"]) & (c > o) & (frame["rel_vol"] >= 1.0) & (
            np.isfinite(previous) & np.isfinite(baseline) & np.isfinite(own_r1))
    elif mechanism == "relative_weakness_exhaustion_rebound":
        required = {"cross_pair_relative_z_previous", "lagged_own_return_1h"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("relative-weakness rebound requires aligned peer history")
        zprev = frame["cross_pair_relative_z_previous"]
        own_r1 = frame["lagged_own_return_1h"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            zprev < -1.60) & (own_r1 < 0.0) & (lo < frame["prior_lo"]) & (
            c > frame["prior_lo"]) & (c > o) & (frame["close_location"] >= .65) & (
            frame["rel_vol"] >= 1.0) & np.isfinite(zprev) & np.isfinite(own_r1)
    elif mechanism == "volatility_leadership_reversal":
        required = {"cross_pair_volatility_ratio", "cross_pair_volatility_ratio_baseline",
                    "lagged_own_return_1h"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("volatility-leadership reversal requires aligned peer history")
        ratio = frame["cross_pair_volatility_ratio"]
        baseline = frame["cross_pair_volatility_ratio_baseline"]
        own_r1 = frame["lagged_own_return_1h"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            ratio > 1.45) & (ratio > baseline * 1.25) & (own_r1 < -.003) & (
            lo < frame["prior_lo"]) & (c > frame["prior_lo"]) & (c > o) & (
            frame["rel_vol"] >= 1.0) & (
            np.isfinite(ratio) & np.isfinite(baseline) & np.isfinite(own_r1))
    elif mechanism == "trend_efficiency_breakout":
        required = {"trend_efficiency_16", "trend_direction_16", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("trend-efficiency mechanism lacks causal path-efficiency features")
        efficiency = frame["trend_efficiency_16"]
        direction = frame["trend_direction_16"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            efficiency >= .42) & (direction > .004) & (c > frame["prior_hi"]) & (
            c > o) & (frame["close_location"] >= .65) & (frame["rel_vol"] >= .95) & (
            np.isfinite(efficiency) & np.isfinite(direction))
    elif mechanism == "serial_dependence_breakout":
        required = {"lagged_return_serial_corr", "lagged_own_return_1h", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("serial-dependence mechanism lacks lagged return history")
        serial = frame["lagged_return_serial_corr"]
        own_r1 = frame["lagged_own_return_1h"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            serial >= .12) & (own_r1 > .001) & (c > frame["prior_hi"]) & (
            c > o) & (frame["close_location"] >= .65) & (frame["rel_vol"] >= .95) & (
            np.isfinite(serial) & np.isfinite(own_r1))
    elif mechanism == "range_wick_absorption_rebound":
        required = {"lagged_lower_wick_absorption", "lower_wick_absorption_baseline",
                    "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("wick-absorption mechanism lacks lagged wick history")
        absorption = frame["lagged_lower_wick_absorption"]
        baseline = frame["lower_wick_absorption_baseline"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            absorption >= .30) & (absorption > baseline * 1.15) & (
            lo < frame["prior_lo"]) & (c > frame["prior_lo"]) & (c > o) & (
            frame["close_location"] >= .65) & (frame["rel_vol"] >= .85) & (
            np.isfinite(absorption) & np.isfinite(baseline))
    elif mechanism == "volatility_of_volatility_release":
        required = {"own_volatility_of_volatility",
                    "own_volatility_of_volatility_baseline", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("vol-of-vol mechanism lacks causal volatility-state history")
        vov = frame["own_volatility_of_volatility"]
        vov_base = frame["own_volatility_of_volatility_baseline"]
        s = (frame["h1_compression"] == 1) & (frame["h1_vol_ok"] == 1) & (
            vov < vov_base * .75) & (c > frame["prior_hi"]) & (c > o) & (
            frame["close_location"] >= .65) & (frame["rel_vol"] >= 1.10) & (
            np.isfinite(vov) & np.isfinite(vov_base))
    elif mechanism == "peer_beta_residual_reclaim":
        required = {"peer_beta_lagged", "lagged_peer_beta_residual",
                    "peer_beta_residual_scale", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("peer-beta residual mechanism requires exact aligned peer history")
        beta = frame["peer_beta_lagged"]
        residual = frame["lagged_peer_beta_residual"]
        scale = frame["peer_beta_residual_scale"]
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            beta > 0.0) & (residual < -1.25 * scale) & (
            lo <= frame["prior_range_mid"]) & (c > frame["prior_range_mid"]) & (
            c > o) & (frame["close_location"] >= .60) & (frame["rel_vol"] >= .90) & (
            np.isfinite(beta) & np.isfinite(residual) & np.isfinite(scale))
    elif mechanism == "prior_day_breakout_continuation":
        required = {"prior_day_high", "prior_day_low", "prior_day_close", "close_location"}
        if not required <= set(frame.columns):
            raise CompositeResearchError("prior-day breakout mechanism lacks completed UTC-day anchors")
        day_high = frame["prior_day_high"]
        s = (frame["h4_up"] == 1) & (frame["h1_vol_ok"] == 1) & (
            c.shift(1) <= day_high) & (c > day_high) & (c > o) & (
            frame["close_location"] >= .65) & (frame["rel_vol"] >= .95) & np.isfinite(day_high)
    elif mechanism == "regime_conditional_composite":
        # A8-style causal regime router. It does not average or optimize
        # historical returns: a completed higher-timeframe state chooses one
        # already-reviewed entry family, while ambiguous/unknown states stay
        # in cash. This is a research hypothesis, never evidence of a new edge
        # or promotion authority by itself.
        trend_regime = (
            (frame["h4_up"] == 1)
            & (frame["h4_range"] == 0)
            & (frame["h1_vol_ok"] == 1)
        )
        range_regime = (
            (frame["h4_range"] == 1)
            & (frame["h4_up"] == 0)
            & (frame["h1_vol_ok"] == 1)
        )
        trend_entry = (
            (lo <= frame["prior_hi"])
            & (c > frame["prior_hi"])
            & (c > o)
            & (frame["rel_vol"] > .85)
        )
        range_failure_entry = (
            (lo < frame["prior_lo"])
            & (c > frame["prior_lo"])
            & (c > o)
            & (frame["rel_vol"] > 1.0)
        )
        s = (trend_regime & trend_entry) | (range_regime & range_failure_entry)
    elif mechanism == "cross_pair_relative_reclaim":
        if not {"cross_pair_relative_z", "cross_pair_relative_z_previous"} <= set(frame.columns):
            raise CompositeResearchError("cross-pair mechanism requires exact aligned verified peer history")
        previous = frame["cross_pair_relative_z_previous"]
        now = frame["cross_pair_relative_z"]
        # A negatively dislocated spot asset starts to recover versus its
        # concurrently closed verified peer, inside already closed 4h/1h
        # non-trending/volatility context. Not paired execution or rotation.
        s = (frame["h4_range"] == 1) & (frame["h1_vol_ok"] == 1) & (
            previous < -1.45) & (now > previous + .20) & (now < -.25) & (
            c > o) & (frame["rel_vol"] >= 1.0) & np.isfinite(now) & np.isfinite(previous)
    else:  # Failed *observed* 15m range break; not imaginary L2 stop hunts.
        s = (frame["h4_range"] == 1) & (lo < frame["prior_lo"]) & (
            c > frame["prior_lo"]) & (c > o) & (frame["rel_vol"] > 1.0)
    return (ok & s).fillna(False).to_numpy(dtype=bool)


def backtest(frame: pd.DataFrame, signals: np.ndarray, *, fee_bps: float,
             slip_bps: float, risk_variant: int) -> dict[str, Any]:
    """Uncapped sequential long-only trades; cash/exposure/daily-loss fail closed.

    The signal on candle i can fill no earlier than next candle i+1 OPEN.
    A bar touching both stop and target exits at the worse (stop) price.
    """
    if len(frame) != len(signals) or risk_variant not in (0, 1):
        raise CompositeResearchError("simulator inputs invalid")
    stop_mult, reward_mult = ((1.5, 2.0), (2.0, 2.5))[risk_variant]
    if fee_bps < 0 or slip_bps < 0:
        raise CompositeResearchError("negative cost assumption")
    cost = (fee_bps + slip_bps) / 10_000.0
    cash, peak, worst_dd = SIM_CASH, SIM_CASH, 0.0
    in_pos, pending, halted, day_paused = None, None, False, False
    day, day_start = None, SIM_CASH
    closed, wins, gross_profit, gross_loss, total_turnover = 0, 0, 0., 0., 0.
    exposure_bars = 0
    for i, row in enumerate(frame.itertuples(index=False)):
        at = pd.Timestamp(row.decision_at)
        if day != at.floor("D"):
            day = at.floor("D")
            day_start, day_paused = cash if in_pos is None else cash + in_pos["qty"] * float(row.open), False
        price_open, price_hi, price_lo, price_close = map(float, (row.open, row.high, row.low, row.close))
        just_entered = False
        if in_pos is None and pending is not None and not halted and not day_paused:
            entry_atr = pending
            pending = None
            entry_price = price_open * (1.0 + slip_bps / 10_000.0)
            stop = entry_price - entry_atr * stop_mult
            target = entry_price + entry_atr * stop_mult * reward_mult
            if stop > 0 and math.isfinite(stop) and math.isfinite(target):
                # Fixed fraction-of-cash and fixed 0.1% stop-risk; never borrowed.
                risk_budget = max(cash, 0) * .001
                qty = min(cash * .10 / (entry_price * (1 + fee_bps / 10_000.0)),
                          risk_budget / (entry_price - stop))
                qty = max(0., qty)
                if qty > 0 and qty * entry_price * (1 + fee_bps / 10_000.0) <= cash:
                    entry_fee = qty * entry_price * fee_bps / 10_000.0
                    cash -= qty * entry_price + entry_fee
                    in_pos = {"qty": qty, "entry": entry_price, "entry_fee": entry_fee,
                              "stop": stop, "target": target, "age": 0}
                    total_turnover += qty * entry_price
                    just_entered = True
        if in_pos is not None:
            exposure_bars += 1
            in_pos["age"] += 1
            exit_at = None
            if price_lo <= in_pos["stop"]:
                exit_at = min(price_open, in_pos["stop"])  # gap and same-bar adverse priority
            elif price_hi >= in_pos["target"]:
                exit_at = in_pos["target"]  # no favorable open-gap price assumption
            elif in_pos["age"] >= 64 or i == len(frame) - 1:
                exit_at = price_close
            if exit_at is not None:
                exit_price = max(0., exit_at * (1.0 - slip_bps / 10_000.0))
                qty = in_pos["qty"]
                exit_fee = qty * exit_price * fee_bps / 10_000.0
                cash += qty * exit_price - exit_fee
                pnl = qty * (exit_price - in_pos["entry"]) - in_pos["entry_fee"] - exit_fee
                gross_profit += max(0., pnl)
                gross_loss += max(0., -pnl)
                wins += (pnl > 0)
                closed += 1
                total_turnover += qty * exit_price
                in_pos = None
        equity = cash + (in_pos["qty"] * price_close if in_pos is not None else 0.)
        peak = max(peak, equity)
        worst_dd = max(worst_dd, 1.0 - equity / peak)
        if equity < day_start * .95:
            day_paused = True
        if worst_dd > .10:
            halted = True
        if in_pos is None and not just_entered and not halted and not day_paused and i < len(frame) - 1:
            if bool(signals[i]) and math.isfinite(float(row.atr)) and float(row.atr) > 0:
                pending = float(row.atr)
    if in_pos is not None:
        raise CompositeResearchError("non-liquidated terminal research position")
    return {
        "net_return_pct": round((cash / SIM_CASH - 1.) * 100., 8),
        "net_pnl_usdt": round(cash - SIM_CASH, 8),
        "max_drawdown_pct": round(worst_dd * 100., 8),
        "closed_round_trips": int(closed),
        "win_rate_pct": (round(wins / closed * 100., 6) if closed else None),
        "profit_factor": (round(gross_profit / gross_loss, 7) if gross_loss > 0 else None),
        "profit_factor_status": "AVAILABLE" if gross_loss > 0 else "NOT_AVAILABLE_NO_REALIZED_LOSSES",
        "turnover_usdt": round(total_turnover, 6),
        "exposure_bar_ratio": round(exposure_bars / len(frame), 6) if len(frame) else 0.,
        "halted_on_drawdown": bool(halted),
        "fee_bps": fee_bps,
        "slippage_bps": slip_bps,
        "trade_count_limit": None,
        "concurrent_risk_model": "one_collateral_backed_net_long_per_symbol;10pct_position_budget",
    }


def empty_ledger() -> dict[str, Any]:
    core = {"schema": LEDGER_SCHEMA, "archive_sha256": ARCHIVE_SHA256,
            "mechanisms_evaluated": [], "config_fingerprints_evaluated": [],
            "research_only": True, "auto_demo_promotion": False, "live_enabled": False}
    return {**core, "ledger_digest": digest(core)}


def load_ledger(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return empty_ledger()
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise CompositeResearchError("invalid novelty ledger object")
    unsigned = dict(obj)
    signed_digest = unsigned.pop("ledger_digest", None)
    screened = unsigned.get("frontier_screened_mechanisms", [])
    screen_version = unsigned.get("frontier_screening_version")
    if (signed_digest != digest(unsigned) or unsigned.get("schema") != LEDGER_SCHEMA
            or unsigned.get("archive_sha256") != ARCHIVE_SHA256
            or unsigned.get("research_only") is not True
            or unsigned.get("auto_demo_promotion") is not False
            or unsigned.get("live_enabled") is not False
            or not isinstance(unsigned.get("config_fingerprints_evaluated"), list)
            or not isinstance(unsigned.get("mechanisms_evaluated"), list)
            or not isinstance(screened, list)
            or len(screened) != len(set(screened))
            or any(item not in FRONTIER_MECHANISMS for item in screened)
            or (screen_version is not None and not isinstance(screen_version, str))):
        raise CompositeResearchError("novelty ledger integrity or authority invalid")
    return obj


def select_next(ledger: dict[str, Any]) -> dict[str, Any] | None:
    seen = ledger["config_fingerprints_evaluated"]
    if len(seen) != len(set(seen)) or any(not isinstance(s, str) for s in seen):
        raise CompositeResearchError("novelty ledger fingerprints malformed")
    # Retained for historical/replay compatibility.  Production run() switches
    # to the frontier tournament once every legacy causal mechanism has been
    # evaluated, rather than cycling through risk variants.
    for novel_only in (True, False):
        for config in CONFIGS:
            if novel_only and config["mechanism"] in ledger["mechanisms_evaluated"]:
                continue
            fingerprint = digest({"config": config, "dataset": ARCHIVE_SHA256, "contract": SCHEMA})
            if fingerprint not in seen:
                return {**config, "fingerprint": fingerprint}
    return None


def _frontier_configs_to_screen(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    evaluated = set(ledger["mechanisms_evaluated"])
    screened = set(ledger.get("frontier_screened_mechanisms", []))
    fixed: list[dict[str, Any]] = []
    generated: list[dict[str, Any]] = []
    generated_ids = set(GENERATED_FACTORY_MECHANISMS)
    for config in FRONTIER_CONFIGS:
        if config["mechanism"] in evaluated or config["mechanism"] in screened:
            continue
        row = {
            **config,
            "fingerprint": digest({
                "config": config, "dataset": ARCHIVE_SHA256, "contract": SCHEMA,
            }),
        }
        (generated if config["mechanism"] in generated_ids else fixed).append(row)
    # Preserve historical reviewed-frontier semantics first.  Once exhausted,
    # advance through deterministic generated topology batches without code edits.
    if fixed:
        return fixed
    return generated[:GENERATED_FRONTIER_BATCH_SIZE]


def research_mode(ledger: dict[str, Any]) -> str:
    """Choose legacy sequential search, one broad frontier screen, or stop."""
    if not set(MECHANISMS).issubset(set(ledger["mechanisms_evaluated"])):
        return "legacy_sequential"
    return "frontier_tournament" if _frontier_configs_to_screen(ledger) else "exhausted"


def has_runnable_candidate(ledger: dict[str, Any]) -> bool:
    mode = research_mode(ledger)
    if mode == "legacy_sequential":
        return select_next(ledger) is not None
    return mode == "frontier_tournament"


def _load_frontier_features(archive_root: Path) -> dict[str, pd.DataFrame]:
    frames_by_symbol = {
        symbol: {
            tf: load_verified_archive_frame(archive_root, symbol, tf)
            for tf in ("minute15", "hour1", "hour4")
        }
        for symbol in SYMBOLS
    }
    if len(SYMBOLS) != 2:
        raise CompositeResearchError("frontier tournament requires reviewed BTC/ETH peer topology")
    return {
        symbol: build_features(
            frames_by_symbol[symbol],
            peer_15m=frames_by_symbol[next(s for s in SYMBOLS if s != symbol)]["minute15"],
        )
        for symbol in SYMBOLS
    }


def _frontier_rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
    # No minimum trade-count gate.  A candidate that never trades cannot outrank
    # an actually exercised system; otherwise breadth and stress resilience lead.
    return (
        -int(row["has_activity"]),
        -int(row["positive_cells"]),
        -float(row["stress_median_return_pct"]),
        -float(row["worst_return_pct"]),
        -float(row["median_return_pct"]),
        float(row["max_drawdown_pct"]),
        row["mechanism"],
    )


def _screen_frontier(
    archive_root: Path, ledger: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, pd.DataFrame] | None]:
    candidates = _frontier_configs_to_screen(ledger)
    if not candidates:
        return None, None, None
    features = _load_frontier_features(archive_root)
    ranking: list[dict[str, Any]] = []
    for candidate in candidates:
        cells = []
        for symbol in SYMBOLS:
            frame = features[symbol]
            cut = int(len(frame) * TRAIN_FRAC)
            signals = signal_for(frame, candidate)
            for profile, (fee, slip) in (
                ("conservative", (ENTRY_FEE_BPS, ENTRY_SLIP_BPS)),
                ("stress", (STRESS_FEE_BPS, STRESS_SLIP_BPS)),
            ):
                result = backtest(
                    frame.iloc[:cut].reset_index(drop=True),
                    signals[:cut],
                    fee_bps=fee,
                    slip_bps=slip,
                    risk_variant=0,
                )
                cells.append({
                    "symbol": symbol,
                    "profile": profile,
                    "bars": cut,
                    "net_return_pct": result["net_return_pct"],
                    "max_drawdown_pct": result["max_drawdown_pct"],
                    "closed_round_trips": result["closed_round_trips"],
                    "profit_factor": result["profit_factor"],
                    "win_rate_pct": result["win_rate_pct"],
                })
        returns = [float(cell["net_return_pct"]) for cell in cells]
        stress_returns = [
            float(cell["net_return_pct"]) for cell in cells if cell["profile"] == "stress"
        ]
        row = {
            "mechanism": candidate["mechanism"],
            "fingerprint": candidate["fingerprint"],
            "has_activity": sum(int(cell["closed_round_trips"]) for cell in cells) > 0,
            "closed_round_trips": sum(int(cell["closed_round_trips"]) for cell in cells),
            "positive_cells": sum(value > 0.0 for value in returns),
            "median_return_pct": round(float(np.median(returns)), 8),
            "stress_median_return_pct": round(float(np.median(stress_returns)), 8),
            "worst_return_pct": round(min(returns), 8),
            "max_drawdown_pct": round(
                max(float(cell["max_drawdown_pct"]) for cell in cells), 8
            ),
            "cells": cells,
        }
        ranking.append(row)
    ranking.sort(key=_frontier_rank_key)
    selected_id = ranking[0]["mechanism"]
    selected = next(item for item in candidates if item["mechanism"] == selected_id)
    for index, row in enumerate(ranking, 1):
        row["rank"] = index
    screening = {
        "schema": FRONTIER_SCREEN_VERSION,
        "basis": "training_partition_only_no_validation_or_historical_test_ranking",
        "candidate_count": len(ranking),
        "shortlist_size": min(FRONTIER_SHORTLIST_SIZE, len(ranking)),
        "shortlist": [row["mechanism"] for row in ranking[:FRONTIER_SHORTLIST_SIZE]],
        "selected_mechanism": selected_id,
        "screened_mechanisms": sorted(row["mechanism"] for row in ranking),
        "no_minimum_trade_count_gate": True,
        "validation_used_for_selection": False,
        "historically_inspected_test_used_for_selection": False,
        "ranking": ranking,
    }
    return selected, screening, features


def run(archive_root: Path, output: Path, source_sha: str, previous: Path | None) -> dict[str, Any]:
    if (len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha)):
        raise CompositeResearchError("source_sha must be exact lower-case git SHA")
    ledger = load_ledger(previous)
    mode = research_mode(ledger)
    screening = None
    feature_cache = None
    if mode == "legacy_sequential":
        nxt = select_next(ledger)
    elif mode == "frontier_tournament":
        nxt, screening, feature_cache = _screen_frontier(archive_root, ledger)
    else:
        nxt = None
    if nxt is None:
        report = {
            "schema": SCHEMA,
            "source_sha": source_sha,
            "archive_sha256": ARCHIVE_SHA256,
            "status": "EXHAUSTED_REQUIRES_NEW_MECHANISM",
            "selection_basis": "no_risk_variant_recycling_after_reviewed_frontier",
            "frontier_screening_version": FRONTIER_SCREEN_VERSION,
            "research_only": True,
            "auto_demo_promotion": False,
            "live_enabled": False,
            "qualification": "NO_NEW_CANDIDATE",
            "rows": [],
        }
        report["report_digest"] = digest(report)
        safe_write(output / "research-report.json", report)
        safe_write(output / "novelty-ledger.json", ledger)
        return report
    rows = []
    for symbol in SYMBOLS:
        if feature_cache is not None:
            f = feature_cache[symbol]
        else:
            frames = {
                tf: load_verified_archive_frame(archive_root, symbol, tf)
                for tf in ("minute15", "hour1", "hour4")
            }
            peer = None
            if nxt["mechanism"] in PEER_MECHANISMS:
                if len(SYMBOLS) != 2:
                    raise CompositeResearchError(
                        "cross-pair peer selection requires reviewed pair topology"
                    )
                other = next(s for s in SYMBOLS if s != symbol)
                peer = load_verified_archive_frame(archive_root, other, "minute15")
            f = build_features(frames, peer_15m=peer)
        sig = signal_for(f, nxt)
        n = len(f)
        cut1, cut2 = int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VALID_FRAC))
        parts = {
            "train": (0, cut1),
            "validation": (cut1, cut2),
            "historically_inspected_test": (cut2, n),
        }
        for name, (lo, hi) in parts.items():
            for kind, (fee, slip) in (
                ("conservative", (ENTRY_FEE_BPS, ENTRY_SLIP_BPS)),
                ("stress", (STRESS_FEE_BPS, STRESS_SLIP_BPS)),
            ):
                result = backtest(
                    f.iloc[lo:hi].reset_index(drop=True),
                    sig[lo:hi],
                    fee_bps=fee,
                    slip_bps=slip,
                    risk_variant=nxt["risk_variant"],
                )
                rows.append({
                    "symbol": symbol,
                    "timeframe": "minute15_with_completed_1h_4h",
                    "mechanism": nxt["mechanism"],
                    "risk_variant": nxt["risk_variant"],
                    "config_fingerprint": nxt["fingerprint"],
                    "part": name,
                    "profile": kind,
                    "bars": hi - lo,
                    "first_closed_utc": str(f["decision_at"].iloc[lo]),
                    "last_closed_utc": str(f["decision_at"].iloc[hi - 1]),
                    **result,
                })
    unsigned = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    unsigned["config_fingerprints_evaluated"] = [
        *unsigned["config_fingerprints_evaluated"], nxt["fingerprint"]
    ]
    unsigned["mechanisms_evaluated"] = sorted(
        set([*unsigned["mechanisms_evaluated"], nxt["mechanism"]])
    )
    if screening is not None:
        unsigned["frontier_screening_version"] = FRONTIER_SCREEN_VERSION
        unsigned["frontier_screened_mechanisms"] = sorted(set([
            *unsigned.get("frontier_screened_mechanisms", []),
            *screening["screened_mechanisms"],
        ]))
    ledger = {**unsigned, "ledger_digest": digest(unsigned)}
    report = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "archive_sha256": ARCHIVE_SHA256,
        "status": "EVALUATED_RESEARCH_ONLY",
        "selection_basis": (
            "frontier_training_only_tournament_then_full_replay"
            if screening is not None
            else "fixed_mechanism_grammar_not_OOS_ranking"
        ),
        "selected": nxt,
        "distinct_mechanisms_tested_cumulative": len(unsigned["mechanisms_evaluated"]),
        "parameter_configs_tested_cumulative": len(unsigned["config_fingerprints_evaluated"]),
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "risk_assumptions": {
            "initial_cash_usdt_per_isolated_run": SIM_CASH,
            "max_position_fraction": .10,
            "max_daily_loss_fraction": .05,
            "max_drawdown_fraction": .10,
            "maximum_trades_per_strategy": None,
        },
        "research_only": True,
        "auto_demo_promotion": False,
        "live_enabled": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": rows,
        "ledger_digest": ledger["ledger_digest"],
    }
    if screening is not None:
        report["frontier_screening"] = screening
    report["report_digest"] = digest(report)
    safe_write(output / "research-report.json", report)
    safe_write(output / "novelty-ledger.json", ledger)
    return report

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--archive-root", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source-sha", required=True)
    ap.add_argument("--previous-ledger", type=Path)
    args = ap.parse_args()
    result = run(args.archive_root, args.output, args.source_sha, args.previous_ledger)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
