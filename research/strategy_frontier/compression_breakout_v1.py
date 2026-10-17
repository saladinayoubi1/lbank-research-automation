"""Fixed historical compression-breakout research frontier; NOT a trading adapter.

Research question: can a previously compressed high/low range followed by
an upward close breakout survive next-open execution and conservative costs?
The official historical archive is already inspected. No independent evidence,
orders, Demo qualification or live trading can be produced by this module.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

SCHEMA = "nexus.strategy-compression-breakout-research.v1"
EXPECTED = {
    "BTCUSDT": ("btc_usdt", "c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226"),
    "ETHUSDT": ("eth_usdt", "ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1"),
}
SOURCE_START = "2022-12-01T00:00:00+00:00"
SOURCE_END = "2026-07-31T23:45:00+00:00"
BARS = 128544
INITIAL_USDT = 500.0
# Freeze four distinct mechanical hypotheses before evaluating the physical source.
ARMS = (
    {"entry_bars": 12, "baseline_bars": 80, "compression_ratio": 0.38, "exit_bars": 8},
    {"entry_bars": 12, "baseline_bars": 80, "compression_ratio": 0.55, "exit_bars": 8},
    {"entry_bars": 20, "baseline_bars": 80, "compression_ratio": 0.38, "exit_bars": 10},
    {"entry_bars": 20, "baseline_bars": 80, "compression_ratio": 0.55, "exit_bars": 10},
)
COSTS = {"conservative": (10, 5), "stress": (25, 15)}
SPLITS = ("training", "validation", "inspected_test")


def digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read_archive(root: Path) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
    frames, receipts = {}, {}
    for symbol, (folder, expected_sha) in EXPECTED.items():
        path = root / "bybit_market" / folder / "minute15.parquet"
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 25_000_000:
            raise ValueError(f"missing/unsafe immutable archive: {symbol}")
        sha = file_hash(path)
        if sha != expected_sha:
            raise ValueError(f"verified original byte hash changed: {symbol}")
        frame = pd.read_parquet(path)
        if frame.columns.tolist() != ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]:
            raise ValueError("historical archive schema mismatch")
        if len(frame) != BARS or set(frame["symbol"]) != {folder} or set(frame["timeframe"]) != {"minute15"}:
            raise ValueError("historical series surface or length mismatch")
        stamp = pd.to_datetime(frame["timestamp"], utc=True)
        if stamp.iloc[0].isoformat() != SOURCE_START or stamp.iloc[-1].isoformat() != SOURCE_END:
            raise ValueError("archive historical range mismatch")
        delta = stamp.diff().dropna().dt.total_seconds()
        if not delta.eq(900).all() or stamp.duplicated().any():
            raise ValueError("historical bars have missing/duplicate timestamps")
        o, h, l, c = (frame[col].to_numpy(dtype=float) for col in ("open", "high", "low", "close"))
        if (not np.isfinite(np.stack((o, h, l, c))).all()
            or np.any(l <= 0) or np.any(l > np.minimum(o, c))
            or np.any(h < np.maximum(o, c))):
            raise ValueError("invalid original closed OHLC")
        frames[symbol] = frame
        receipts[symbol] = sha
    return frames, receipts


def targets(frame: pd.DataFrame, config: dict) -> np.ndarray:
    if set(config) != {"entry_bars", "baseline_bars", "compression_ratio", "exit_bars"}:
        raise ValueError("unexpected signal configuration")
    n, b, ratio, exit_n = (config[k] for k in ("entry_bars", "baseline_bars", "compression_ratio", "exit_bars"))
    if (type(n) is not int or type(b) is not int or type(exit_n) is not int
        or not 5 <= exit_n < n < b <= 200 or type(ratio) not in (int, float)
        or not 0 < float(ratio) < 1):
        raise ValueError("invalid preregistered signal parameters")
    high, low, close = (frame[k].astype(float) for k in ("high", "low", "close"))
    recent_high = high.shift(1).rolling(n, min_periods=n).max()
    recent_low = low.shift(1).rolling(n, min_periods=n).min()
    base_high = high.shift(1).rolling(b, min_periods=b).max()
    base_low = low.shift(1).rolling(b, min_periods=b).min()
    exit_floor = low.shift(1).rolling(exit_n, min_periods=exit_n).min()
    compressed = (recent_high - recent_low) < float(ratio) * (base_high - base_low)
    entry = (compressed & (close > recent_high)).fillna(False).to_numpy(dtype=bool)
    exit_rule = (close < exit_floor).fillna(False).to_numpy(dtype=bool)
    output = np.zeros(len(frame), dtype=np.int8)
    state = 0
    for i in range(len(frame)):
        if state and exit_rule[i]:
            state = 0
        elif not state and entry[i]:
            state = 1
        output[i] = state
    return output


def simulate(frame: pd.DataFrame, signals: np.ndarray, start: int, end: int,
             fee_bps: float, slip_bps: float) -> dict:
    if len(signals) != len(frame) or not 0 <= start < end <= len(frame) or end - start < 2:
        raise ValueError("invalid research simulation partition")
    opened = frame["open"].to_numpy(float)
    closed = frame["close"].to_numpy(float)
    fee, slip = fee_bps / 10000.0, slip_bps / 10000.0
    cash, qty = INITIAL_USDT, 0.0
    previous_entry_cash = 0.0
    realized = []
    equities = []
    entry_count, forced_exits = 0, 0
    for i in range(start, end):
        if i > start:  # Current bar's close signal cannot trade at its own open.
            last_target = int(signals[i - 1])
            if last_target and qty == 0:
                previous_entry_cash = cash
                notional = cash / (1 + fee)
                qty = notional / (opened[i] * (1 + slip))
                cash = 0.0
                entry_count += 1
            elif not last_target and qty > 0:
                cash = qty * opened[i] * (1 - slip) * (1 - fee)
                qty = 0.0
                realized.append(cash - previous_entry_cash)
        equities.append(cash + qty * closed[i])
    if qty > 0:
        cash = qty * closed[end - 1] * (1 - slip) * (1 - fee)
        qty = 0.0
        realized.append(cash - previous_entry_cash)
        equities[-1] = cash
        forced_exits = 1
    equity = np.asarray(equities)
    if not np.isfinite(equity).all() or np.any(equity < 0):
        raise ValueError("invalid simulated research capital")
    highwater = np.maximum.accumulate(equity)
    return {
        "initial_usdt": INITIAL_USDT,
        "closed_roundtrips": len(realized),
        "entries": entry_count,
        "forced_end_exits": forced_exits,
        "net_pnl_usdt": round(cash - INITIAL_USDT, 8),
        "mean_closed_trade_usdt": round(sum(realized) / len(realized), 8) if realized else None,
        "positive_closed_trades": sum(p > 0 for p in realized),
        "negative_closed_trades": sum(p < 0 for p in realized),
        "maximum_drawdown_fraction": round(float(np.max(1 - equity / highwater)), 8),
    }


def evaluate(frames: dict[str, pd.DataFrame], hashes: dict[str, str]) -> dict:
    length = {len(frame) for frame in frames.values()}
    if set(frames) != set(EXPECTED) or len(length) != 1 or length.pop() != BARS:
        raise ValueError("both exact physical BTC/ETH sources are mandatory")
    bounds = ((0, int(BARS * .6)), (int(BARS * .6), int(BARS * .8)),
              (int(BARS * .8), BARS))
    arms = []
    for config in ARMS:
        outcomes = {}
        for symbol, frame in frames.items():
            signal = targets(frame, config)
            outcomes[symbol] = {
                name: {profile: simulate(frame, signal, start, end, *cost)
                       for profile, cost in COSTS.items()}
                for name, (start, end) in zip(SPLITS, bounds)
            }
        train = sum(outcomes[s]["training"]["conservative"]["net_pnl_usdt"] for s in EXPECTED)
        arms.append({"config": config, "training_net_pnl_both_usdt": round(train, 8),
                     "per_symbol": outcomes})
    selected = sorted(range(len(arms)), key=lambda i: (-arms[i]["training_net_pnl_both_usdt"], i))[0]
    core = {
        "schema": SCHEMA, "scope": "HISTORICAL_INSPECTED_EXPLORATORY_ONLY",
        "source": "previously_reviewed_immutable_bybit_spot_15m_archive",
        "source_files_sha256": hashes,
        "original_bars_per_symbol": BARS, "symbols": list(EXPECTED),
        "partitions": [{"name": n, "start": a, "end_exclusive": b}
                       for n, (a, b) in zip(SPLITS, bounds)],
        "arms": arms, "training_only_selected_arm_index": selected,
        "no_minimum_trade_count": True,
        "no_unseen_holdout_or_proven_profit": True,
        "source_originally_inspected": True,
        "entry_rule": "close-confirmed breakout, execute next bar OPEN",
        "exit_rule": "close-confirmed trailing low or forced partition end",
        "intrabar_stops_or_target_simulated": False,
        "actual_orders": 0, "paper_eligible": False,
        "demo_modified": False, "automatic_promotion": False,
        "live_enabled": False,
    }
    return {**core, "result_sha256": digest(core)}


def main() -> None:
    cli = argparse.ArgumentParser()
    cli.add_argument("--archive-root", type=Path, required=True)
    cli.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    frames, hashes = read_archive(args.archive_root)
    result = evaluate(frames, hashes)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("write-once source-bound research output already exists")
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "HISTORICAL_RESEARCH_COMPLETED_NOT_QUALIFIED",
                      "selected_training_arm": result["training_only_selected_arm_index"],
                      "result_sha256": result["result_sha256"],
                      "arms": len(result["arms"]), "orders": 0,
                      "paper_eligible": False}, sort_keys=True))


if __name__ == "__main__":
    main()
