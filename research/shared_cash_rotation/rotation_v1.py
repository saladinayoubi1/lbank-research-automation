"""Shared-cash cross-asset *exploratory* Bybit Spot rotation, NO trade authority.

One fixed preregistered topology, not a tunable Strategy Finder sweep:
15m closed BTC/ETH rank -> next open, sell-before-buy in ONE cash book.
Historical 2022-2026 data are already inspected; not a pristine holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA = "nexus.shared-cash-relative-rotation-research.v1"
SYMBOLS = ("BTC", "ETH")
CASH = 500.0
INTERVAL = 16  # Every 4h, BTC and ETH decisions reference already CLOSED 15m bars.
MAX_HOLD_BARS = 96  # 24 hours, exit at next open; cooldown 4 hours.
LOOKBACK = 16
BTC_GUARD = 48
MOMENTUM_MIN = 0.005
RANK_GAP_MIN = 0.002
BTC_CRASH_GUARD = -0.02
STOP_FRACTION = 0.015  # hard stop, 1.5% from actual buy execution price
CONSERVATIVE = (10.0, 5.0)   # per-side fee and slippage, basis points
STRESS = (25.0, 15.0)
EXPECTED_ROW_COUNT = 128544
START_TIME = "2022-12-01T00:00:00+00:00"
END_TIME = "2026-07-31T23:45:00+00:00"


class RotationResearchError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as fp:
        fp.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        fp.flush()
        os.fsync(fp.fileno())
    os.replace(temp, path)


def verified_frame(path: Path, sha: str, symbol: str) -> pd.DataFrame:
    if path.is_symlink() or not path.is_file() or not (
        isinstance(sha, str) and len(sha) == 64 and
        all(c in "0123456789abcdef" for c in sha)
    ):
        raise RotationResearchError("unverified pinned source identity")
    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
        raise RotationResearchError("immutable source file SHA256 mismatch")
    frame = pd.read_parquet(path)
    mandatory = {"timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"}
    if set(frame.columns) != mandatory or len(frame) != EXPECTED_ROW_COUNT:
        raise RotationResearchError("source OHLCV grid and scope differ from pinned manifest")
    if not (frame["symbol"] == symbol.lower() + "_usdt").all() or not (
        frame["timeframe"] == "minute15"
    ).all():
        raise RotationResearchError("source symbol or timeframe mismatch")
    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if (
        ts.iloc[0].isoformat() != START_TIME or ts.iloc[-1].isoformat() != END_TIME
        or ts.duplicated().any() or not ts.is_monotonic_increasing
        or not (ts.diff().iloc[1:] == pd.Timedelta(minutes=15)).all()
    ):
        raise RotationResearchError("incomplete or unaligned candle chronology")
    nums = frame[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)
    if (
        not np.isfinite(nums).all()
        or (nums[:, :4] <= 0).any() or (nums[:, 4] < 0).any()
        or (nums[:, 1] < np.maximum.reduce((nums[:, 0], nums[:, 2], nums[:, 3]))).any()
        or (nums[:, 2] > np.minimum.reduce((nums[:, 0], nums[:, 1], nums[:, 3]))).any()
    ):
        raise RotationResearchError("OHLCV values invalid")
    return frame.reset_index(drop=True)


def as_arrays(frames: dict[str, pd.DataFrame]) -> dict[str, dict[str, np.ndarray]]:
    if set(frames) != set(SYMBOLS):
        raise RotationResearchError("exact BTC and ETH data required")
    left = pd.to_datetime(frames["BTC"]["timestamp"], utc=True)
    right = pd.to_datetime(frames["ETH"]["timestamp"], utc=True)
    if not left.equals(right):
        raise RotationResearchError("cross-asset UTC bar alignment missing")
    return {
        sym: {field: frames[sym][field].to_numpy(dtype=float)
              for field in ("open", "high", "low", "close")}
        for sym in SYMBOLS
    }


def rank_at_closed_bar(data: dict[str, dict[str, np.ndarray]], closed: int) -> str | None:
    """Only candle <= closed can affect the NEXT candle's open fill."""
    if closed < max(LOOKBACK, BTC_GUARD):
        return None
    btc = data["BTC"]["close"]
    eth = data["ETH"]["close"]
    market = btc[closed] / btc[closed - BTC_GUARD] - 1.0
    if market < BTC_CRASH_GUARD:
        return None
    momentum = {
        "BTC": btc[closed] / btc[closed - LOOKBACK] - 1.0,
        "ETH": eth[closed] / eth[closed - LOOKBACK] - 1.0,
    }
    leader = "BTC" if momentum["BTC"] >= momentum["ETH"] else "ETH"
    if momentum[leader] < MOMENTUM_MIN or abs(momentum["BTC"] - momentum["ETH"]) < RANK_GAP_MIN:
        return None
    return leader


def replay(data: dict[str, dict[str, np.ndarray]], timestamps: pd.Series,
           start: int, end: int, *, fee_bps: float, slip_bps: float) -> dict[str, Any]:
    """One book, no simultaneous longs, actual fills ONLY at next open or hard stop."""
    if (
        not 0 <= start < end <= len(timestamps) or end - start < 96
        or fee_bps < 0 or slip_bps < 0 or not math.isfinite(fee_bps + slip_bps)
        or fee_bps + slip_bps >= 5000
    ):
        raise RotationResearchError("invalid replay partition or friction")
    fee, slip = fee_bps / 10000.0, slip_bps / 10000.0
    cash, held, qty, paid, stop, opened_at = CASH, None, 0.0, 0.0, 0.0, -1
    cooldown_until = start
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    peak, worst_dd = CASH, 0.0
    fees_total = 0.0
    switch_count = 0

    def sell(index: int, raw: float, cause: str) -> None:
        nonlocal cash, held, qty, paid, stop, opened_at, fees_total
        assert held is not None and qty > 0.0
        px = raw * (1.0 - slip)
        gross = qty * px
        exit_fee = gross * fee
        net = gross - exit_fee
        pnl = net - paid
        fees_total += exit_fee
        cash = net
        trades.append({
            "symbol": held, "entry_index": opened_at, "exit_index": index,
            "exit_time_utc": pd.Timestamp(timestamps.iloc[index]).isoformat(),
            "exit_reason": cause, "net_pnl_usdt": round(pnl, 8),
            "entry_spend_usdt": round(paid, 8), "exit_proceeds_usdt": round(net, 8),
            "exit_fill_price": round(px, 8),
        })
        events.append({"index": index, "event": "SELL", "symbol": held, "reason": cause})
        held, qty, paid, stop, opened_at = None, 0.0, 0.0, 0.0, -1

    for i in range(start, end):
        # Partition end is known ahead of time, so terminal exit is *precommitted*
        # and uses the final candle OPEN, not its unknown close.
        due = (i == start or (i - start) % INTERVAL == 0)
        target = held
        if i == end - 1:
            target = None
        elif due:
            target = rank_at_closed_bar(data, i - 1)
        if held is not None and i - opened_at >= MAX_HOLD_BARS:
            target = None
            cooldown_until = max(cooldown_until, i + INTERVAL)
        if i < cooldown_until:
            target = None
        original = held
        if held is not None and target != held:
            sell(i, float(data[held]["open"][i]), "terminal" if i == end - 1
                 else "rank_change_or_timeout")
        if original is not None and target is not None and target != original:
            switch_count += 1
        if target is not None and held is None and i < end - 1 and i >= cooldown_until:
            raw = float(data[target]["open"][i])
            px = raw * (1.0 + slip)
            # Actual buy fee is paid FROM the single shared cash book.
            notional = cash / (1.0 + fee)
            entry_fee = notional * fee
            qty = notional / px
            paid = notional + entry_fee
            fees_total += entry_fee
            cash -= paid
            held, opened_at, stop = target, i, px * (1.0 - STOP_FRACTION)
            events.append({"index": i, "event": "BUY", "symbol": target})
        if held is not None:
            raw_open = float(data[held]["open"][i])
            raw_low = float(data[held]["low"][i])
            if raw_low <= stop:
                sell(i, min(raw_open, stop), "hard_stop_stop_first")
                cooldown_until = max(cooldown_until, i + INTERVAL)
        mark = cash if held is None else cash + qty * float(data[held]["close"][i])
        peak = max(peak, mark)
        worst_dd = max(worst_dd, (peak - mark) / peak * 100.0)
        if cash < -1e-7 or qty < 0:
            raise RotationResearchError("shared book overallocated or borrowed")
    if held is not None or qty != 0 or cash < 0:
        raise RotationResearchError("open position escaped finite partition")
    monthly = defaultdict(lambda: {"round_trips": 0, "net_pnl_usdt": 0.0})
    for trade in trades:
        key = trade["exit_time_utc"][:7]
        monthly[key]["round_trips"] += 1
        monthly[key]["net_pnl_usdt"] += trade["net_pnl_usdt"]
    monthly_rows = [{
        "month": month, "round_trips": value["round_trips"],
        "net_pnl_usdt": round(value["net_pnl_usdt"], 8),
        "mean_pnl_usdt": round(value["net_pnl_usdt"] / value["round_trips"], 8),
    } for month, value in sorted(monthly.items())]
    return {
        "start_time_utc": pd.Timestamp(timestamps.iloc[start]).isoformat(),
        "end_time_utc": pd.Timestamp(timestamps.iloc[end - 1]).isoformat(),
        "initial_cash_usdt": CASH, "ending_cash_usdt": round(cash, 8),
        "net_pnl_usdt": round(cash - CASH, 8),
        "net_return_pct": round((cash / CASH - 1.0) * 100.0, 8),
        "round_trips": len(trades), "mean_pnl_usdt": round(
            sum(t["net_pnl_usdt"] for t in trades) / len(trades), 8
        ) if trades else None,
        "switch_count": switch_count, "max_drawdown_pct": round(worst_dd, 8),
        "fee_paid_usdt": round(fees_total, 8),
        "monthly": monthly_rows, "trades": trades,
        "events": events,
    }


def execute(btc: Path, eth: Path, sha_btc: str, sha_eth: str) -> dict[str, Any]:
    frames = {"BTC": verified_frame(btc, sha_btc, "BTC"),
              "ETH": verified_frame(eth, sha_eth, "ETH")}
    data = as_arrays(frames)
    times = frames["BTC"]["timestamp"]
    n = len(times)
    bounds = {
        "training": (BTC_GUARD + 2, int(n * 0.60)),
        "validation_already_inspected": (int(n * 0.60), int(n * 0.80)),
        "historical_test_already_inspected": (int(n * 0.80), n),
    }
    results = {}
    for label, (start, end) in bounds.items():
        results[label] = {
            profile: replay(data, times, start, end, fee_bps=fee, slip_bps=slip)
            for profile, (fee, slip) in (
                ("conservative", CONSERVATIVE), ("stress", STRESS),
            )
        }
    spec = {
        "schema": SCHEMA, "strategy": "shared_cash_btc_eth_4h_relative_leader_rotation",
        "btc_sha256": sha_btc, "eth_sha256": sha_eth,
        "source_candles_per_asset": n,
        "source_start_utc": START_TIME, "source_end_utc": END_TIME,
        "starting_shared_cash_usdt": CASH, "rank_lookback_bars": LOOKBACK,
        "allocation_decision_every_bars": INTERVAL, "btc_guard_bars": BTC_GUARD,
        "momentum_min": MOMENTUM_MIN, "rank_gap_min": RANK_GAP_MIN,
        "btc_crash_guard": BTC_CRASH_GUARD, "hard_stop_fraction": STOP_FRACTION,
        "max_hold_bars": MAX_HOLD_BARS,
        "conservative_per_side_fee_slippage_bps": list(CONSERVATIVE),
        "stress_per_side_fee_slippage_bps": list(STRESS),
        "simulation_only": True, "training_only_selection": True,
        "historical_holdouts_already_inspected": True,
        "novelty_independently_certified": False,
        "qualification_authority": False,
        "automatic_demo_promotion": False,
        "live_trading_authority": False,
    }
    output = {
        **spec, "config_digest": _digest(spec),
        "results": results,
        "decision": "EXPLORATORY_RESEARCH_NO_PROMOTION",
        "next_step": "independent_semantic_overlap_review_and_future_unseen_qa",
    }
    return {**output, "result_digest": _digest(output)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--btc-sha256", required=True)
    parser.add_argument("--eth-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve() in (args.btc.resolve(), args.eth.resolve()):
        raise RotationResearchError("do not overwrite immutable source")
    result = execute(args.btc, args.eth, args.btc_sha256, args.eth_sha256)
    _write(args.output, result)
    print(json.dumps({
        "decision": result["decision"], "result_digest": result["result_digest"],
        "summaries": {
            stage: {name: {k:v for k,v in report.items() if k in (
                "net_pnl_usdt", "round_trips", "mean_pnl_usdt", "max_drawdown_pct"
            )} for name, report in values.items()}
            for stage, values in result["results"].items()
        },
        "automatic_demo_promotion": False, "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
