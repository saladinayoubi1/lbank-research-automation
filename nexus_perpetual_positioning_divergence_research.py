"""Source-bound Research-only A9 perpetual positioning divergence evaluation.

Spot long/cash is the only execution model. Verified public Bybit perpetual
funding and one-hour single-sided OI are context inputs only. No derivative
execution, Paper promotion, or Live authority is granted by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import bybit_spot_backfill as spot_backfill
import nexus_a9_spot_source as a9_spot_source
from nexus_verified_perpetual_positioning import (
    OI_INTERVAL,
    OI_METHOD_CHANGE,
    SYMBOLS as POSITIONING_SYMBOLS,
    semantic_digest as positioning_semantic_digest,
    verify_funding,
    verify_open_interest_grid,
    verify_proof as verify_positioning_proof,
)

SCHEMA = "nexus.perpetual-positioning-divergence-research.v2"
MECHANISM = "perpetual_positioning_divergence"
SPOT_TO_LINEAR = {"btc_usdt": "BTCUSDT", "eth_usdt": "ETHUSDT"}
START = pd.Timestamp("2026-07-03T00:00:00Z")
END_EXCLUSIVE = pd.Timestamp("2026-08-02T00:00:00Z")
STEP = pd.Timedelta(minutes=15)
EXPECTED_BARS = int((END_EXCLUSIVE - START) / STEP)
EXPECTED_POSITIONING_DIGEST = "a59405c733ecc6cad5c9270155a22bab52173989cd62c9569cf37b06f844c6e6"
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
FUNDING_LOW_Q = 0.25
OI_GROWTH_HIGH_Q = 0.75
SIM_CASH = 10_000.0
POSITION_FRACTION = 0.10
RISK_FRACTION = 0.001
MAX_DAILY_LOSS = 0.05
MAX_DRAWDOWN = 0.10
TIME_EXIT_BARS = 16
STOP_ATR = 1.5
TARGET_ATR = 2.0
COST_PROFILES = {
    "conservative": (10.0, 5.0),
    "stress": (25.0, 15.0),
}


class PositioningResearchError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 25_000_000:
        raise PositioningResearchError(f"unsafe source file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def utc(values: Any) -> pd.Series:
    result = pd.Series(pd.to_datetime(values, utc=True, errors="raise"))
    if result.isna().any():
        raise PositioningResearchError("missing timestamp")
    return result.astype("datetime64[ns, UTC]")


def _funding_interval_map(proof: dict[str, Any]) -> dict[str, int]:
    rows = proof.get("instrument_contracts")
    if not isinstance(rows, list):
        raise PositioningResearchError("positioning proof instrument contracts missing")
    result: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise PositioningResearchError("invalid positioning instrument contract")
        symbol = str(row.get("symbol", ""))
        minutes = int(row.get("funding_interval_minutes", 0))
        if symbol not in POSITIONING_SYMBOLS or minutes <= 0:
            raise PositioningResearchError("invalid positioning funding contract")
        result[symbol] = minutes
    if set(result) != set(POSITIONING_SYMBOLS):
        raise PositioningResearchError("incomplete positioning funding contracts")
    return result


def load_verified_positioning(root: Path) -> tuple[dict[str, dict[str, pd.DataFrame]], dict[str, Any]]:
    root = root.resolve()
    proof_path = root / "_perpetual_positioning_proof.json"
    if proof_path.is_symlink() or not proof_path.is_file() or proof_path.stat().st_size > 1_000_000:
        raise PositioningResearchError("verified positioning proof missing or unsafe")
    try:
        proof = json.loads(proof_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PositioningResearchError("verified positioning proof unreadable") from exc
    verify_positioning_proof(proof)
    if (
        proof.get("dataset_semantic_sha256") != EXPECTED_POSITIONING_DIGEST
        or proof.get("oi_interval") != OI_INTERVAL == "1h"
        or proof.get("oi_value_field") != "singleOpenInterest"
        or proof.get("oi_methodology") != "post_2026_06_11_single_sided"
        or proof.get("start_utc") != START.isoformat()
        or proof.get("end_exclusive_utc") != END_EXCLUSIVE.isoformat()
        or proof.get("symbols") != list(POSITIONING_SYMBOLS)
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("derivatives_execution_authority") is not False
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("live_trading_authority") is not False
        or proof.get("credentials_used") is not False
    ):
        raise PositioningResearchError("positioning proof does not match the accepted A9 source contract")

    intervals = _funding_interval_map(proof)
    data: dict[str, dict[str, pd.DataFrame]] = {}
    oi_for_digest: dict[str, pd.DataFrame] = {}
    funding_for_digest: dict[str, pd.DataFrame] = {}
    for symbol in POSITIONING_SYMBOLS:
        folder = root / symbol.lower()
        oi_path = folder / "open_interest_1h.parquet"
        funding_path = folder / "funding_settlements.parquet"
        for path in (oi_path, funding_path):
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 25_000_000:
                raise PositioningResearchError(f"verified positioning frame missing or unsafe: {path}")
        oi = verify_open_interest_grid(pd.read_parquet(oi_path), symbol, START, END_EXCLUSIVE)
        funding = verify_funding(
            pd.read_parquet(funding_path),
            symbol,
            START,
            END_EXCLUSIVE,
            intervals[symbol],
        )
        oi_for_digest[symbol] = oi
        funding_for_digest[symbol] = funding
        data[symbol] = {"oi": oi, "funding": funding}

    if positioning_semantic_digest(oi_for_digest, funding_for_digest) != EXPECTED_POSITIONING_DIGEST:
        raise PositioningResearchError("positioning frames do not match verified semantic digest")
    return data, proof


def load_spot_proof(root: Path) -> dict[str, Any]:
    root = root.resolve()
    path = root / a9_spot_source.PROOF_NAME
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise PositioningResearchError("official A9 Spot proof missing or unsafe")
    try:
        proof = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PositioningResearchError("official A9 Spot proof unreadable") from exc
    try:
        a9_spot_source.verify_proof(root, proof)
    except a9_spot_source.A9SpotSourceError as exc:
        raise PositioningResearchError("official A9 Spot proof rejected") from exc
    if (
        proof.get("source_window_start") != "2026-07-03"
        or proof.get("source_window_end_inclusive") != "2026-08-01"
        or proof.get("analysis_start_utc") != START.isoformat()
        or proof.get("analysis_end_exclusive_utc") != END_EXCLUSIVE.isoformat()
        or proof.get("symbols") != ["BTCUSDT", "ETHUSDT"]
        or proof.get("data_origin") != "official_public_bybit_spot_trade_archive_aggregated"
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("live_trading_authority") is not False
        or proof.get("private_credentials_used") is not False
        or proof.get("real_exchange_orders") is not False
    ):
        raise PositioningResearchError("Spot source proof authority or analysis window rejected")
    return proof


def load_spot(state_root: Path, symbol: str) -> pd.DataFrame:
    path = state_root.resolve() / "bybit_market" / symbol / "minute15.parquet"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 500_000_000:
        raise PositioningResearchError(f"official Spot frame missing or unsafe: {symbol}")
    frame = pd.read_parquet(path).copy()
    required = ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    if frame.columns.tolist() != required:
        raise PositioningResearchError(f"unexpected Spot schema for {symbol}")
    frame["timestamp"] = utc(frame["timestamp"])
    frame = frame[(frame["timestamp"] >= START) & (frame["timestamp"] < END_EXCLUSIVE)].copy()
    frame = frame.sort_values("timestamp").reset_index(drop=True)
    expected = pd.date_range(START, END_EXCLUSIVE, freq=STEP, inclusive="left")
    if (
        len(frame) != EXPECTED_BARS
        or not pd.DatetimeIndex(frame["timestamp"]).equals(expected)
        or set(frame["symbol"].astype(str)) != {symbol}
        or set(frame["timeframe"].astype(str)) != {"minute15"}
    ):
        raise PositioningResearchError(f"Spot 15m grid is incomplete for {symbol}")
    for name in ("open", "high", "low", "close", "volume"):
        frame[name] = pd.to_numeric(frame[name], errors="raise")
    values = frame[["open", "high", "low", "close", "volume"]].astype(float).to_numpy()
    if not np.isfinite(values).all():
        raise PositioningResearchError(f"non-finite Spot values for {symbol}")
    if (
        (frame[["open", "high", "low", "close"]] <= 0).any().any()
        or (frame["volume"] < 0).any()
        or (frame["high"] < frame[["open", "close", "low"]].max(axis=1)).any()
        or (frame["low"] > frame[["open", "close", "high"]].min(axis=1)).any()
    ):
        raise PositioningResearchError(f"invalid Spot OHLCV values for {symbol}")
    frame["decision_at"] = frame["timestamp"] + STEP
    return frame


def prepare_symbol(
    spot_state_root: Path,
    spot_symbol: str,
    positioning: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    spot = load_spot(spot_state_root, spot_symbol)
    oi = positioning["oi"].copy()
    funding = positioning["funding"].copy()

    oi = oi.rename(
        columns={
            "timestamp": "oi_timestamp",
            "available_at": "oi_available_at",
            "single_open_interest": "open_interest_observed",
        }
    )
    oi["oi_timestamp"] = utc(oi["oi_timestamp"])
    oi["oi_available_at"] = utc(oi["oi_available_at"])
    oi = oi[
        ["oi_timestamp", "oi_available_at", "open_interest_observed", "oi_methodology"]
    ].sort_values("oi_available_at")

    funding = funding.rename(
        columns={
            "timestamp": "funding_timestamp",
            "available_at": "funding_available_at",
        }
    )
    funding["funding_timestamp"] = utc(funding["funding_timestamp"])
    funding["funding_available_at"] = utc(funding["funding_available_at"])
    funding = funding[
        ["funding_timestamp", "funding_available_at", "funding_rate"]
    ].sort_values("funding_available_at")

    frame = pd.merge_asof(
        spot.sort_values("decision_at"),
        oi,
        left_on="decision_at",
        right_on="oi_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    frame = pd.merge_asof(
        frame.sort_values("decision_at"),
        funding,
        left_on="decision_at",
        right_on="funding_available_at",
        direction="backward",
        allow_exact_matches=True,
    )

    if (
        (frame["oi_available_at"].dropna() > frame.loc[frame["oi_available_at"].notna(), "decision_at"]).any()
        or (frame["funding_available_at"].dropna() > frame.loc[frame["funding_available_at"].notna(), "decision_at"]).any()
    ):
        raise PositioningResearchError("future positioning context leaked into A9 decision time")

    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - prev_close).abs(),
            (frame["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    frame["atr"] = tr.rolling(14, min_periods=14).mean()
    frame["price_return_4h"] = frame["close"] / frame["close"].shift(16) - 1.0
    frame["oi_growth_4h"] = (
        frame["open_interest_observed"] / frame["open_interest_observed"].shift(16) - 1.0
    )
    return frame


def training_thresholds(frame: pd.DataFrame, train_end: int) -> dict[str, float]:
    train = frame.iloc[:train_end]
    funding = train["funding_rate"].replace([np.inf, -np.inf], np.nan).dropna()
    oi_growth = train["oi_growth_4h"].replace([np.inf, -np.inf], np.nan).dropna()
    if len(funding) < 1000 or len(oi_growth) < 1000:
        raise PositioningResearchError("insufficient train positioning observations")
    result = {
        "funding_low_q25": float(funding.quantile(FUNDING_LOW_Q)),
        "funding_median": float(funding.median()),
        "oi_growth_high_q75": float(oi_growth.quantile(OI_GROWTH_HIGH_Q)),
    }
    if not all(math.isfinite(x) for x in result.values()):
        raise PositioningResearchError("non-finite A9 training threshold")
    return result


def build_signal(frame: pd.DataFrame, threshold: dict[str, float]) -> np.ndarray:
    prior = (
        (frame["funding_rate"].shift(1) <= threshold["funding_low_q25"])
        & (frame["oi_growth_4h"].shift(1) >= threshold["oi_growth_high_q75"])
        & (frame["oi_growth_4h"].shift(1) > 0.0)
        & (frame["price_return_4h"].shift(1) <= 0.0)
    )
    response = (
        (frame["close"] > frame["high"].shift(1))
        & (frame["close"] > frame["open"])
    )
    valid = (
        frame["atr"].notna()
        & frame["funding_rate"].notna()
        & frame["oi_growth_4h"].notna()
    )
    return (prior & response & valid).fillna(False).to_numpy(dtype=bool)


def invalidation(frame: pd.DataFrame, threshold: dict[str, float]) -> np.ndarray:
    value = (
        (frame["funding_rate"] > threshold["funding_median"])
        | (frame["oi_growth_4h"] < 0.0)
    )
    return value.fillna(False).to_numpy(dtype=bool)


def simulate(
    frame: pd.DataFrame,
    signals: np.ndarray,
    invalid: np.ndarray,
    *,
    fee_bps: float,
    slip_bps: float,
) -> dict[str, Any]:
    if len(frame) != len(signals) or len(frame) != len(invalid):
        raise PositioningResearchError("simulator vectors do not match frame")
    fee = fee_bps / 10_000.0
    slip = slip_bps / 10_000.0
    cash = peak = SIM_CASH
    position: dict[str, float] | None = None
    pending_entry = False
    pending_exit = False
    pending_atr = 0.0
    day = None
    day_start = SIM_CASH
    day_paused = False
    halted = False
    closed = wins = exposure = 0
    gross_profit = gross_loss = turnover = 0.0
    worst_dd = 0.0

    def close_position(raw_price: float) -> None:
        nonlocal cash, position, closed, wins, gross_profit, gross_loss, turnover
        assert position is not None
        exit_price = max(0.0, raw_price * (1.0 - slip))
        qty = position["qty"]
        exit_fee = qty * exit_price * fee
        cash += qty * exit_price - exit_fee
        pnl = qty * (exit_price - position["entry"]) - position["entry_fee"] - exit_fee
        gross_profit += max(0.0, pnl)
        gross_loss += max(0.0, -pnl)
        wins += int(pnl > 0.0)
        closed += 1
        turnover += qty * exit_price
        position = None

    for i, row in enumerate(frame.itertuples(index=False)):
        at = pd.Timestamp(row.decision_at)
        op, hi, lo, cl = map(float, (row.open, row.high, row.low, row.close))
        current_day = at.floor("D")
        if day != current_day:
            day = current_day
            day_start = cash if position is None else cash + position["qty"] * op
            day_paused = False

        if pending_exit and position is not None:
            close_position(op)
        pending_exit = False

        if pending_entry and position is None and not halted and not day_paused:
            entry = op * (1.0 + slip)
            stop = entry - STOP_ATR * pending_atr
            target = entry + TARGET_ATR * pending_atr
            if pending_atr > 0.0 and stop > 0.0:
                risk_budget = max(cash, 0.0) * RISK_FRACTION
                qty = min(
                    cash * POSITION_FRACTION / (entry * (1.0 + fee)),
                    risk_budget / max(entry - stop, 1e-12),
                )
                if qty > 0.0 and qty * entry * (1.0 + fee) <= cash:
                    entry_fee = qty * entry * fee
                    cash -= qty * entry + entry_fee
                    turnover += qty * entry
                    position = {
                        "qty": qty,
                        "entry": entry,
                        "entry_fee": entry_fee,
                        "stop": stop,
                        "target": target,
                        "age": 0.0,
                    }
        pending_entry = False

        if position is not None:
            exposure += 1
            position["age"] += 1
            if lo <= position["stop"]:
                close_position(min(op, position["stop"]))
            elif hi >= position["target"]:
                close_position(position["target"])
            elif i == len(frame) - 1:
                close_position(cl)
            elif invalid[i] or position["age"] >= TIME_EXIT_BARS:
                pending_exit = True

        equity = cash + (position["qty"] * cl if position is not None else 0.0)
        peak = max(peak, equity)
        worst_dd = max(worst_dd, 1.0 - equity / peak)
        if equity < day_start * (1.0 - MAX_DAILY_LOSS):
            day_paused = True
        if worst_dd > MAX_DRAWDOWN:
            halted = True

        if (
            i < len(frame) - 1
            and signals[i]
            and position is None
            and not pending_entry
            and not halted
            and not day_paused
            and math.isfinite(float(row.atr))
        ):
            pending_entry = True
            pending_atr = float(row.atr)

    pf = gross_profit / gross_loss if gross_loss > 0 else (math.inf if gross_profit > 0 else 0.0)
    return {
        "starting_cash_usdt": SIM_CASH,
        "ending_cash_usdt": round(cash, 8),
        "net_return_pct": round((cash / SIM_CASH - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(worst_dd * 100.0, 6),
        "closed_trades": int(closed),
        "win_rate_pct": round((wins / closed * 100.0) if closed else 0.0, 6),
        "profit_factor": round(pf, 6) if math.isfinite(pf) else "inf",
        "turnover_usdt": round(turnover, 6),
        "exposure_bar_ratio": round(exposure / len(frame), 6) if len(frame) else 0.0,
        "halted_on_drawdown": bool(halted),
        "fee_bps": fee_bps,
        "slippage_bps": slip_bps,
        "trade_count_limit": None,
        "execution_instrument": "spot_long_or_cash_only",
    }


def spot_semantic_digest(frames: dict[str, pd.DataFrame]) -> str:
    payload: dict[str, Any] = {}
    for symbol in sorted(frames):
        frame = frames[symbol]
        payload[symbol] = [
            {
                "timestamp": pd.Timestamp(row.timestamp).isoformat(),
                "open": round(float(row.open), 12),
                "high": round(float(row.high), 12),
                "low": round(float(row.low), 12),
                "close": round(float(row.close), 12),
                "volume": round(float(row.volume), 12),
            }
            for row in frame.itertuples(index=False)
        ]
    return digest(payload)


def evaluate(
    spot_state_root: Path,
    spot_proof_root: Path,
    positioning_root: Path,
    source_sha: str,
) -> dict[str, Any]:
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise PositioningResearchError("source_sha must be exact lower-case git SHA")
    spot_proof = load_spot_proof(spot_proof_root)
    positioning, positioning_proof = load_verified_positioning(positioning_root)

    rows: list[dict[str, Any]] = []
    thresholds: dict[str, dict[str, float]] = {}
    spot_frames: dict[str, pd.DataFrame] = {}
    for spot_symbol, linear_symbol in SPOT_TO_LINEAR.items():
        raw_spot = load_spot(spot_state_root, spot_symbol)
        spot_frames[spot_symbol] = raw_spot[
            ["timestamp", "open", "high", "low", "close", "volume"]
        ].copy()
        frame = prepare_symbol(spot_state_root, spot_symbol, positioning[linear_symbol])
        n = len(frame)
        cut1 = int(n * TRAIN_FRAC)
        cut2 = int(n * (TRAIN_FRAC + VALID_FRAC))
        threshold = training_thresholds(frame, cut1)
        thresholds[spot_symbol] = {key: round(value, 12) for key, value in threshold.items()}
        signals = build_signal(frame, threshold)
        invalid = invalidation(frame, threshold)

        parts = {
            "train": (0, cut1),
            "validation": (cut1, cut2),
            "historically_inspected_test": (cut2, n),
        }
        for part, (lo, hi) in parts.items():
            local = frame.iloc[lo:hi].reset_index(drop=True)
            for profile, (fee, slip) in COST_PROFILES.items():
                rows.append(
                    {
                        "symbol": spot_symbol,
                        "context_contract": linear_symbol,
                        "timeframe": "minute15",
                        "mechanism": MECHANISM,
                        "part": part,
                        "profile": profile,
                        "bars": hi - lo,
                        "signals": int(signals[lo:hi].sum()),
                        "first_decision_utc": pd.Timestamp(local["decision_at"].iloc[0]).isoformat(),
                        "last_decision_utc": pd.Timestamp(local["decision_at"].iloc[-1]).isoformat(),
                        **simulate(
                            local,
                            signals[lo:hi],
                            invalid[lo:hi],
                            fee_bps=fee,
                            slip_bps=slip,
                        ),
                    }
                )

    source_manifest = spot_state_root.resolve() / spot_backfill.SOURCE_MANIFEST_NAME
    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "mechanism": MECHANISM,
        "selection_basis": "pre_registered_A9_positioning_divergence_not_OOS_ranking",
        "start_utc": START.isoformat(),
        "end_exclusive_utc": END_EXCLUSIVE.isoformat(),
        "threshold_method": "per_symbol_train_only_funding_q25_median_and_verified_1h_single_oi_growth_q75",
        "thresholds": thresholds,
        "spot_archive_source_manifest_sha256": file_sha256(source_manifest),
        "spot_archive_source_proof_sha256": spot_proof["proof_sha256"],
        "spot_semantic_sha256": spot_semantic_digest(spot_frames),
        "positioning_dataset_semantic_sha256": positioning_proof["dataset_semantic_sha256"],
        "positioning_proof_sha256": positioning_proof["proof_sha256"],
        "positioning_oi_interval": positioning_proof["oi_interval"],
        "positioning_oi_value_field": positioning_proof["oi_value_field"],
        "positioning_oi_methodology": positioning_proof["oi_methodology"],
        "execution_model": "closed_15m_spot_context;verified_1h_OI_available_after_interval;signal_on_close;entry_and_signal_exit_next_open",
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "derivative_execution_authority": False,
        "live_trading_authority": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": rows,
    }
    return {**core, "report_sha256": digest(core)}


def run(
    spot_state_root: Path,
    spot_proof_root: Path,
    positioning_root: Path,
    output: Path,
    source_sha: str,
) -> dict[str, Any]:
    report = evaluate(
        spot_state_root,
        spot_proof_root,
        positioning_root,
        source_sha,
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "perpetual-positioning-divergence-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    if START < OI_METHOD_CHANGE:
        raise PositioningResearchError("A9 source window crosses OI methodology boundary")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spot-state-root", type=Path, required=True)
    parser.add_argument("--spot-proof-root", type=Path, required=True)
    parser.add_argument("--positioning-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    report = run(
        args.spot_state_root,
        args.spot_proof_root,
        args.positioning_root,
        args.output,
        args.source_sha,
    )
    print(
        json.dumps(
            {
                "mechanism": report["mechanism"],
                "qualification": report["qualification"],
                "rows": len(report["rows"]),
                "positioning_dataset_semantic_sha256": report["positioning_dataset_semantic_sha256"],
                "research_only": report["research_only"],
                "auto_promotion": report["automatic_strategy_promotion"],
                "derivative_execution_authority": report["derivative_execution_authority"],
                "live_authority": report["live_trading_authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
