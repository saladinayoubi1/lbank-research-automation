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
from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame

SCHEMA = "nexus.automatic-composite-research.v1"
LEDGER_SCHEMA = "nexus.automatic-composite-novelty-ledger.v1"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
MECHANISMS = (
    "structural_pullback",
    "volatility_compression_expansion",
    "bar_proxy_vwap_reclaim",
    "failed_range_break_reversal",
)
# Distinct entry mechanisms vs risk/feature parameter variations are explicitly
# separately labeled; eight configurations do NOT count as eight new edges.
CONFIGS = tuple(
    {"mechanism": mechanism, "risk_variant": v, "entry_model": "closed_4h_1h_15m_next_open"}
    for mechanism in MECHANISMS for v in (0, 1)
)
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


def build_features(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
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
    f["rel_vol"] = volume / volume.shift(1).rolling(20, min_periods=20).mean().replace(0, np.nan)
    f["atr"] = (f["high"] - f["low"]).shift(1).rolling(14, min_periods=14).mean()
    return f


def signal_for(frame: pd.DataFrame, config: dict[str, Any]) -> np.ndarray:
    mechanism = config["mechanism"]
    if mechanism not in MECHANISMS or config["risk_variant"] not in (0, 1):
        raise CompositeResearchError("unreviewed strategy grammar")
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
    if (signed_digest != digest(unsigned) or unsigned.get("schema") != LEDGER_SCHEMA
            or unsigned.get("archive_sha256") != ARCHIVE_SHA256
            or unsigned.get("research_only") is not True
            or unsigned.get("auto_demo_promotion") is not False
            or unsigned.get("live_enabled") is not False
            or not isinstance(unsigned.get("config_fingerprints_evaluated"), list)
            or not isinstance(unsigned.get("mechanisms_evaluated"), list)):
        raise CompositeResearchError("novelty ledger integrity or authority invalid")
    return obj


def select_next(ledger: dict[str, Any]) -> dict[str, Any] | None:
    seen = ledger["config_fingerprints_evaluated"]
    if len(seen) != len(set(seen)) or any(not isinstance(s, str) for s in seen):
        raise CompositeResearchError("novelty ledger fingerprints malformed")
    for config in CONFIGS:
        fingerprint = digest({"config": config, "dataset": ARCHIVE_SHA256, "contract": SCHEMA})
        if fingerprint not in seen:
            return {**config, "fingerprint": fingerprint}
    return None


def run(archive_root: Path, output: Path, source_sha: str, previous: Path | None) -> dict[str, Any]:
    if (len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha)):
        raise CompositeResearchError("source_sha must be exact lower-case git SHA")
    ledger = load_ledger(previous)
    nxt = select_next(ledger)
    if nxt is None:
        report = {"schema": SCHEMA, "source_sha": source_sha, "archive_sha256": ARCHIVE_SHA256,
                  "status": "EXHAUSTED_REQUIRES_NEW_MECHANISM",
                  "research_only": True, "auto_demo_promotion": False, "live_enabled": False,
                  "qualification": "NO_NEW_CANDIDATE", "rows": []}
        report["report_digest"] = digest(report)
        safe_write(output / "research-report.json", report)
        safe_write(output / "novelty-ledger.json", ledger)
        return report
    rows = []
    for symbol in SYMBOLS:
        frames = {tf: load_verified_archive_frame(archive_root, symbol, tf)
                  for tf in ("minute15", "hour1", "hour4")}
        f = build_features(frames)
        sig = signal_for(f, nxt)
        n = len(f)
        cut1, cut2 = int(n * TRAIN_FRAC), int(n * (TRAIN_FRAC + VALID_FRAC))
        parts = {"train": (0, cut1), "validation": (cut1, cut2), "historically_inspected_test": (cut2, n)}
        for name, (lo, hi) in parts.items():
            for kind, (fee, slip) in (
                ("conservative", (ENTRY_FEE_BPS, ENTRY_SLIP_BPS)),
                ("stress", (STRESS_FEE_BPS, STRESS_SLIP_BPS))):
                # Prior candle history is visible for causal features; no trading
                # position/equity carries across evaluation splits.
                result = backtest(f.iloc[lo:hi].reset_index(drop=True), sig[lo:hi],
                                  fee_bps=fee, slip_bps=slip, risk_variant=nxt["risk_variant"])
                rows.append({"symbol": symbol, "timeframe": "minute15_with_completed_1h_4h",
                             "mechanism": nxt["mechanism"], "risk_variant": nxt["risk_variant"],
                             "config_fingerprint": nxt["fingerprint"], "part": name,
                             "profile": kind, "bars": hi - lo,
                             "first_closed_utc": str(f["decision_at"].iloc[lo]),
                             "last_closed_utc": str(f["decision_at"].iloc[hi - 1]),
                             **result})
    unsigned = {k: v for k, v in ledger.items() if k != "ledger_digest"}
    unsigned["config_fingerprints_evaluated"] = [*unsigned["config_fingerprints_evaluated"], nxt["fingerprint"]]
    unsigned["mechanisms_evaluated"] = sorted(set([*unsigned["mechanisms_evaluated"], nxt["mechanism"]]))
    ledger = {**unsigned, "ledger_digest": digest(unsigned)}
    report = {"schema": SCHEMA, "source_sha": source_sha, "archive_sha256": ARCHIVE_SHA256,
              "status": "EVALUATED_RESEARCH_ONLY", "selection_basis": "fixed_mechanism_grammar_not_OOS_ranking",
              "selected": nxt, "distinct_mechanisms_tested_cumulative": len(unsigned["mechanisms_evaluated"]),
              "parameter_configs_tested_cumulative": len(unsigned["config_fingerprints_evaluated"]),
              "historical_test_pristine": False, "independent_future_data_required": True,
              "risk_assumptions": {"initial_cash_usdt_per_isolated_run": SIM_CASH,
                                   "max_position_fraction": .10, "max_daily_loss_fraction": .05,
                                   "max_drawdown_fraction": .10, "maximum_trades_per_strategy": None},
              "research_only": True, "auto_demo_promotion": False, "live_enabled": False,
              "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
              "rows": rows, "ledger_digest": ledger["ledger_digest"]}
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
