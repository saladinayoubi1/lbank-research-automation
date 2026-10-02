"""Research-only A6 signed taker-flow / price-response strategy evaluation.

Uses only verified official Bybit Spot 15m candles and privacy-safe signed-flow
aggregates. The strategy is long/flat, fills entries and signal-driven exits no
earlier than next bar open, and has no Paper/Demo/Live promotion authority.
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

from nexus_verified_signed_trade_flow import verify_proof

SCHEMA = "nexus.signed-flow-price-response-research.v1"
MECHANISM = "signed_flow_price_response"
SYMBOLS = ("btc_usdt", "eth_usdt")
MIN_BARS = 30 * 96
TRAIN_FRAC = 0.60
VALID_FRAC = 0.20
SIM_CASH = 10_000.0
POSITION_FRACTION = 0.10
RISK_FRACTION = 0.001
MAX_DAILY_LOSS = 0.05
MAX_DRAWDOWN = 0.10
FLOW_QUANTILE = 0.80
TIME_EXIT_BARS = 16
STOP_ATR = 1.5
TARGET_ATR = 2.0
COST_PROFILES = {
    "conservative": (10.0, 5.0),
    "stress": (25.0, 15.0),
}


class SignedFlowResearchError(ValueError):
    pass


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise SignedFlowResearchError("proof unavailable, linked, or oversized")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SignedFlowResearchError("proof must be a JSON object")
    return value


def _load_all(root: Path) -> dict[str, Any]:
    proof = _json(root / "_signed_trade_flow_proof.json")
    flows: dict[str, pd.DataFrame] = {}
    all_flow = []
    for symbol in SYMBOLS:
        folder = root / symbol
        candle_path = folder / "minute15.parquet"
        flow_path = folder / "signed_trade_flow_15m.parquet"
        if not candle_path.is_file() or not flow_path.is_file():
            raise SignedFlowResearchError(f"missing verified A6 inputs for {symbol}")
        candles = pd.read_parquet(candle_path)
        flow = pd.read_parquet(flow_path)
        if candles.empty or flow.empty:
            raise SignedFlowResearchError(f"empty A6 inputs for {symbol}")
        flows[symbol] = flow
        all_flow.append(flow)
    verify_proof(pd.concat(all_flow, ignore_index=True), proof)

    if (
        proof.get("capability") != "verified_signed_trade_flow"
        or proof.get("research_only") is not True
        or proof.get("paper_only") is not True
        or proof.get("automatic_strategy_promotion") is not False
        or proof.get("live_trading_authority") is not False
    ):
        raise SignedFlowResearchError("signed-flow proof authority rejected")
    return {"proof": proof, "flows": flows}


def prepare_symbol(root: Path, symbol: str, flow: pd.DataFrame) -> pd.DataFrame:
    candles = pd.read_parquet(root / symbol / "minute15.parquet").copy()
    for frame in (candles, flow):
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    candles = candles.sort_values("timestamp").reset_index(drop=True)
    flow = flow.sort_values("timestamp").reset_index(drop=True)
    if len(candles) != len(flow) or not candles["timestamp"].equals(flow["timestamp"]):
        raise SignedFlowResearchError(f"candle/flow timestamp identity mismatch for {symbol}")
    if len(candles) < MIN_BARS:
        raise SignedFlowResearchError(
            f"{symbol} needs at least {MIN_BARS} 15m bars for 30-day evaluation"
        )
    expected_available = flow["timestamp"] + pd.Timedelta(minutes=15)
    actual_available = pd.to_datetime(flow["available_at"], utc=True, errors="raise")
    if not actual_available.equals(expected_available):
        raise SignedFlowResearchError(f"non-causal signed-flow availability for {symbol}")

    merged = candles[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    for name in (
        "buy_notional", "sell_notional", "total_notional",
        "signed_notional", "signed_notional_imbalance", "trade_count", "vwap",
    ):
        merged[name] = pd.to_numeric(flow[name], errors="raise")
    merged["decision_at"] = merged["timestamp"] + pd.Timedelta(minutes=15)

    previous_close = merged["close"].shift(1)
    tr = pd.concat(
        [
            merged["high"] - merged["low"],
            (merged["high"] - previous_close).abs(),
            (merged["low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    merged["atr"] = tr.rolling(14, min_periods=14).mean()
    signed_1h = merged["signed_notional"].rolling(4, min_periods=4).sum()
    total_1h = merged["total_notional"].rolling(4, min_periods=4).sum()
    merged["flow_1h"] = signed_1h / total_1h.replace(0.0, np.nan)
    merged["price_return_1h"] = merged["close"] / merged["close"].shift(4) - 1.0
    return merged


def training_threshold(frame: pd.DataFrame, train_end: int) -> float:
    values = frame.loc[: train_end - 1, "flow_1h"]
    values = values[np.isfinite(values) & (values > 0)]
    if len(values) < 100:
        raise SignedFlowResearchError("insufficient positive training flow observations")
    threshold = float(values.quantile(FLOW_QUANTILE))
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise SignedFlowResearchError("invalid training-only flow threshold")
    return threshold


def build_signal(frame: pd.DataFrame, threshold: float) -> np.ndarray:
    prior_divergence = (
        (frame["flow_1h"].shift(1) >= threshold)
        & (frame["price_return_1h"].shift(1) <= 0.0)
    )
    response = (
        (frame["close"] > frame["high"].shift(1))
        & (frame["close"] > frame["open"])
        & (frame["flow_1h"] > 0.0)
    )
    valid = frame["atr"].notna() & frame["flow_1h"].notna()
    return (prior_divergence & response & valid).fillna(False).to_numpy(dtype=bool)


def simulate(
    frame: pd.DataFrame,
    signals: np.ndarray,
    *,
    fee_bps: float,
    slip_bps: float,
) -> dict[str, Any]:
    if len(frame) != len(signals) or fee_bps < 0 or slip_bps < 0:
        raise SignedFlowResearchError("invalid simulator inputs")
    fee = fee_bps / 10_000.0
    slip = slip_bps / 10_000.0
    cash = peak = SIM_CASH
    worst_dd = 0.0
    position = None
    pending_entry = None
    pending_exit = False
    day = None
    day_start = SIM_CASH
    day_paused = False
    halted = False
    closed = wins = exposure_bars = 0
    gross_profit = gross_loss = turnover = 0.0

    def close_position(raw_price: float) -> float:
        nonlocal cash, position, closed, wins, gross_profit, gross_loss, turnover
        exit_price = max(0.0, raw_price * (1.0 - slip))
        qty = position["qty"]
        exit_fee = qty * exit_price * fee
        cash += qty * exit_price - exit_fee
        pnl = qty * (exit_price - position["entry"]) - position["entry_fee"] - exit_fee
        gross_profit += max(0.0, pnl)
        gross_loss += max(0.0, -pnl)
        wins += int(pnl > 0)
        closed += 1
        turnover += qty * exit_price
        position = None
        return pnl

    for i, row in enumerate(frame.itertuples(index=False)):
        at = pd.Timestamp(row.decision_at)
        price_open, price_high, price_low, price_close = map(
            float, (row.open, row.high, row.low, row.close)
        )
        if day != at.floor("D"):
            day = at.floor("D")
            day_start = cash if position is None else cash + position["qty"] * price_open
            day_paused = False

        if pending_exit and position is not None:
            close_position(price_open)
        pending_exit = False

        if pending_entry is not None and position is None and not halted and not day_paused:
            atr = float(pending_entry["atr"])
            entry_price = price_open * (1.0 + slip)
            stop = entry_price - STOP_ATR * atr
            target = entry_price + TARGET_ATR * atr
            if atr > 0 and stop > 0 and entry_price > stop:
                risk_budget = max(cash, 0.0) * RISK_FRACTION
                qty = min(
                    cash * POSITION_FRACTION / (entry_price * (1.0 + fee)),
                    risk_budget / (entry_price - stop),
                )
                if qty > 0 and qty * entry_price * (1.0 + fee) <= cash:
                    entry_fee = qty * entry_price * fee
                    cash -= qty * entry_price + entry_fee
                    position = {
                        "qty": qty, "entry": entry_price, "entry_fee": entry_fee,
                        "stop": stop, "target": target, "age": 0,
                    }
                    turnover += qty * entry_price
        pending_entry = None

        if position is not None:
            exposure_bars += 1
            position["age"] += 1
            exit_at = None
            if price_low <= position["stop"]:
                exit_at = min(price_open, position["stop"])
            elif price_high >= position["target"]:
                exit_at = position["target"]
            if exit_at is not None:
                close_position(exit_at)
            elif i == len(frame) - 1:
                close_position(price_close)
            elif float(row.flow_1h) <= 0.0 or position["age"] >= TIME_EXIT_BARS:
                pending_exit = True

        equity = cash + (position["qty"] * price_close if position is not None else 0.0)
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
            and pending_entry is None
            and not halted
            and not day_paused
            and math.isfinite(float(row.atr))
        ):
            pending_entry = {"atr": float(row.atr), "signal_at": str(at)}

    net_return = cash / SIM_CASH - 1.0
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0
        else (math.inf if gross_profit > 0 else 0.0)
    )
    return {
        "starting_cash_usdt": SIM_CASH,
        "ending_cash_usdt": round(cash, 8),
        "net_return_pct": round(net_return * 100.0, 6),
        "max_drawdown_pct": round(worst_dd * 100.0, 6),
        "closed_trades": int(closed),
        "win_rate_pct": round((wins / closed * 100.0) if closed else 0.0, 6),
        "profit_factor": round(profit_factor, 6) if math.isfinite(profit_factor) else "inf",
        "turnover_usdt": round(turnover, 6),
        "exposure_bar_ratio": round(exposure_bars / len(frame), 6) if len(frame) else 0.0,
        "halted_on_drawdown": bool(halted),
        "fee_bps": fee_bps,
        "slippage_bps": slip_bps,
        "trade_count_limit": None,
        "position_model": "one_collateral_backed_long_or_cash;10pct_position_budget",
    }


def run(root: Path, output: Path, source_sha: str) -> dict[str, Any]:
    if len(source_sha) != 40 or any(c not in "0123456789abcdef" for c in source_sha):
        raise SignedFlowResearchError("source_sha must be exact lower-case git SHA")
    loaded = _load_all(root)
    proof = loaded["proof"]
    rows = []
    thresholds = {}
    for symbol in SYMBOLS:
        frame = prepare_symbol(root, symbol, loaded["flows"][symbol])
        n = len(frame)
        cut1 = int(n * TRAIN_FRAC)
        cut2 = int(n * (TRAIN_FRAC + VALID_FRAC))
        if cut1 < 1 or cut2 <= cut1 or cut2 >= n:
            raise SignedFlowResearchError("invalid chronological split")
        threshold = training_threshold(frame, cut1)
        thresholds[symbol] = threshold
        signals = build_signal(frame, threshold)
        parts = {
            "train": (0, cut1),
            "validation": (cut1, cut2),
            "historically_inspected_test": (cut2, n),
        }
        for part, (lo, hi) in parts.items():
            part_frame = frame.iloc[lo:hi].reset_index(drop=True)
            part_signals = signals[lo:hi]
            for profile, (fee, slip) in COST_PROFILES.items():
                result = simulate(part_frame, part_signals, fee_bps=fee, slip_bps=slip)
                rows.append({
                    "symbol": symbol,
                    "timeframe": "minute15",
                    "mechanism": MECHANISM,
                    "part": part,
                    "profile": profile,
                    "bars": hi - lo,
                    "first_decision_utc": str(part_frame["decision_at"].iloc[0]),
                    "last_decision_utc": str(part_frame["decision_at"].iloc[-1]),
                    "flow_threshold_train_q80": round(threshold, 8),
                    "signals": int(part_signals.sum()),
                    **result,
                })

    core = {
        "schema": SCHEMA,
        "source_sha": source_sha,
        "mechanism": MECHANISM,
        "selection_basis": "pre_registered_signed_flow_price_response_not_OOS_ranking",
        "signed_flow_proof_sha256": proof["proof_sha256"],
        "signed_flow_dataset_sha256": proof["dataset_semantic_sha256"],
        "start_date": proof["start_date"],
        "end_date": proof["end_date"],
        "threshold_method": "per_symbol_train_only_positive_flow_1h_q80",
        "thresholds": {k: round(v, 8) for k, v in thresholds.items()},
        "execution_model": "decision_on_closed_15m_bar;entry_and_flow_exit_next_open",
        "historical_test_pristine": False,
        "independent_future_data_required": True,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "qualification": "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT",
        "rows": rows,
    }
    report = {**core, "report_sha256": digest(core)}
    output.mkdir(parents=True, exist_ok=True)
    path = output / "signed-flow-price-response-report.json"
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    report = run(args.input_root, args.output, args.source_sha)
    print(json.dumps({
        "mechanism": report["mechanism"],
        "qualification": report["qualification"],
        "rows": len(report["rows"]),
        "research_only": report["research_only"],
        "auto_promotion": report["automatic_strategy_promotion"],
        "live_authority": report["live_trading_authority"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
