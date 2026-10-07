"""Owner-requested fixed 10-strategy historical comparison; no Paper admission.

Public Bybit spot, long/flat, independent 500 USDT accounts. Signals use closed
bars and execute next open. History is previously inspected, NOT an untouched
holdout. Fractional research sizing does not certify exchange lot executability.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_engine import BacktestConfig
from bybit_public_klines import fetch_closed_klines
from canonical_backtest import canonical_market_frame, run_canonical_target_exposure_backtest
from market_data_source_validator import load_and_validate
from phase6_research_pipeline import bind_bybit_closed_dataset
from product_research_runtime import _public_mapping, _registry_path, TIMEFRAMES

START = pd.Timestamp("2026-08-26T00:00:00Z")
END = pd.Timestamp("2026-09-25T00:00:00Z")
WARMUP = 500
STRATEGIES = ("ema20_50", "donchian20_10", "bollinger20_2", "rsi14_30_50",
              "macd12_26_9", "supertrend10_3", "keltner20_2", "vwap_ema50",
              "adx14_donchian20", "momentum20_ema100")
PROFILES = {"conservative": (10.0, 5.0), "stress": (25.0, 15.0)}
CONTRACT = {
    "schema": "nexus.monthly-ten-strategies.v1", "start": START.isoformat(),
    "end_exclusive": END.isoformat(), "warmup_bars": WARMUP,
    "strategies": list(STRATEGIES), "symbols": ["BTCUSDT", "ETHUSDT"],
    "timeframes": ["minute15", "hour1", "hour4"], "costs_bps_per_leg": PROFILES,
    "initial_cash_usdt": 500, "market": "spot", "direction": "long_flat",
    "sizing": "100_percent_cost_aware_fractional_no_leverage",
    "execution": "next_open", "terminal_exit": "last_scored_close_with_costs",
    "per_strategy_minimum_trades_gate": None, "automatic_promotion": False,
    "live_trading_authority": False, "independent_holdout": False,
    "exchange_lot_size_validated": False,
}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False), "utf-8")
    temporary.replace(path)


def _held(entry, exit_):
    state = False
    output = []
    for enter, leave in zip(entry.fillna(False), exit_.fillna(False)):
        if state and leave:
            state = False
        elif not state and enter:
            state = True
        output.append(float(state))
    return pd.Series(output, index=entry.index)


def targets(frame, strategy):
    if strategy not in STRATEGIES:
        raise ValueError("unregistered strategy")
    c, h, l = (frame[k].astype(float) for k in ("close", "high", "low"))
    ema = lambda n: c.ewm(span=n, adjust=False, min_periods=n).mean()
    tr = pd.concat([h-l, (h-c.shift()).abs(), (l-c.shift()).abs()], axis=1).max(axis=1)
    atr = lambda n: tr.ewm(alpha=1/n, adjust=False, min_periods=n).mean()
    upper = h.shift().rolling(20).max()
    lower = l.shift().rolling(10).min()
    if strategy == "ema20_50":
        result = (ema(20) > ema(50)).astype(float)
    elif strategy == "donchian20_10":
        result = _held(c > upper, c < lower)
    elif strategy == "bollinger20_2":
        middle = c.rolling(20).mean()
        result = _held(c < middle-2*c.rolling(20).std(ddof=0), c >= middle)
    elif strategy == "rsi14_30_50":
        delta = c.diff()
        up = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        down = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        rsi = 100*up/(up+down).replace(0, np.nan)
        result = _held((rsi < 30) & (c > ema(200)), (rsi >= 50) | (c < ema(200)))
    elif strategy == "macd12_26_9":
        macd = ema(12)-ema(26)
        result = (macd > macd.ewm(span=9, adjust=False, min_periods=9).mean()).astype(float)
    elif strategy == "supertrend10_3":
        basic_u, basic_l = (h+l)/2+3*atr(10), (h+l)/2-3*atr(10)
        last_u = last_l = None
        bullish = False
        values = []
        for i in range(len(c)):
            if not np.isfinite(basic_u.iloc[i]):
                values.append(0.0)
                continue
            bu, bl = basic_u.iloc[i], basic_l.iloc[i]
            if last_u is None:
                fu, fl = bu, bl
            else:
                fu = bu if bu < last_u or c.iloc[i-1] > last_u else last_u
                fl = bl if bl > last_l or c.iloc[i-1] < last_l else last_l
                if bullish and c.iloc[i] < fl:
                    bullish = False
                elif not bullish and c.iloc[i] > fu:
                    bullish = True
            last_u, last_l = fu, fl
            values.append(float(bullish))
        result = pd.Series(values, index=c.index)
    elif strategy == "keltner20_2":
        result = _held(c > ema(20)+2*atr(20), c < ema(20))
    elif strategy == "vwap_ema50":
        volume = frame["volume"].astype(float)
        day = pd.to_datetime(frame["timestamp"], utc=True).dt.floor("D")
        vwap = (((h+l+c)/3*volume).groupby(day).cumsum()
                / volume.groupby(day).cumsum().replace(0, np.nan))
        recovery = (c > vwap) & (c.shift() <= vwap.shift()) & (day == day.shift())
        result = _held(recovery & (c > ema(50)), (c < vwap) | (c < ema(50)))
    elif strategy == "adx14_donchian20":
        plus, minus = h.diff(), -l.diff()
        plus = plus.where((plus > minus) & (plus > 0), 0.0)
        minus = minus.where((minus > h.diff()) & (minus > 0), 0.0)
        smooth = lambda s: s.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
        pdi, mdi = 100*smooth(plus)/atr(14), 100*smooth(minus)/atr(14)
        adx = smooth(100*(pdi-mdi).abs()/(pdi+mdi).replace(0, np.nan))
        result = _held((adx > 25) & (c > upper), c < lower)
    else:
        result = ((c.pct_change(20) > 0) & (c > ema(100))).astype(float)
    return result.fillna(0.0)


def summarize(result):
    """Round trips include explicit terminal liquidation, not rebalance counts."""
    trades, cost, position = [], 0.0, 0.0
    entries = exits = 0
    for row in result.fills.to_dict("records"):
        delta = float(row["quantity_change"])
        if delta > 0:
            if position <= 1e-12:
                entries += 1
            cost += float(row["notional"])+float(row["fee"])
        else:
            cost -= float(row["notional"])-float(row["fee"])
        position = float(row["position_after"])
        if delta < 0 and abs(position) <= 1e-12:
            trades.append(-cost)
            cost = 0.0
            exits += 1
    pnl = float(result.metrics["net_pnl"])
    if abs(position) > 1e-12 or not np.isclose(sum(trades), pnl, atol=1e-6):
        raise ValueError("round-trip ledger does not reconcile")
    return {**result.metrics, "entries": entries, "exits": exits,
            "completed_trades": len(trades), "wins": sum(x > 1e-8 for x in trades),
            "losses": sum(x < -1e-8 for x in trades),
            "breakeven": sum(abs(x) <= 1e-8 for x in trades),
            "gross_winning_net_trades": sum(x for x in trades if x > 0),
            "gross_losing_net_trades": sum(x for x in trades if x < 0),
            "unrealized_pnl": 0.0, "open_positions": 0,
            "funding_cost": 0.0, "funding_reason": "spot_no_funding",
            "forced_terminal_exits": int(sum(result.fills["reason"] == "end_liquidation"))}


def collect(symbol, timeframe, root):
    spec = TIMEFRAMES[timeframe]
    step = spec["step_ms"]
    first = int(START.timestamp()*1000)-WARMUP*step
    last = int(END.timestamp()*1000)-step
    mapping, source = _public_mapping(load_and_validate(_registry_path()), symbol, timeframe)
    path = root / f"dataset-{symbol}-{timeframe}.json"
    if path.exists():
        dataset = json.loads(path.read_text("utf-8"))
    else:
        candles = []
        for lo in range(first, last+step, 1000*step):
            hi = min(last, lo+999*step)
            page_path = root / f"page-{symbol}-{timeframe}-{lo}.json"
            if page_path.exists():
                page = json.loads(page_path.read_text("utf-8"))
                # Revalidate a resumed page through the same canonical boundary.
                canonical_market_frame(bind_bybit_closed_dataset(page,
                    canonical_symbol=mapping["canonical_symbol"], source_symbol=source["symbol"],
                    interval=spec["interval"]), registry_path=_registry_path())
            else:
                page = fetch_closed_klines(symbol, spec["interval"],
                    now_ms=int(END.timestamp()*1000), start_time_ms=lo, end_time_ms=hi,
                    limit=(hi-lo)//step+1, timeout_seconds=20)
                write_json(page_path, page)
            if [x["open_time_ms"] for x in page] != list(range(lo, hi+step, step)):
                raise ValueError("page coverage mismatch")
            candles.extend(page)
        dataset = bind_bybit_closed_dataset(candles,
            canonical_symbol=mapping["canonical_symbol"], source_symbol=source["symbol"],
            interval=spec["interval"])
        write_json(path, dataset)
    artifact, frame = canonical_market_frame(dataset, registry_path=_registry_path())
    if (artifact["source_symbol"] != symbol or artifact["manifest_timeframe"] != spec["manifest"]
            or [x["open_time_ms"] for x in artifact["rows"]] != list(range(first, last+step, step))):
        raise ValueError("dataset identity/window mismatch")
    frame["volume"] = [float(x["volume"]) for x in artifact["rows"]]
    return artifact, frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    contract = json.loads(json.dumps({**CONTRACT,
        "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}))
    freeze = root / "preregistered-contract.json"
    if freeze.exists() and json.loads(freeze.read_text("utf-8")) != contract:
        raise ValueError("output belongs to a different frozen experiment")
    write_json(freeze, contract)
    cells = []
    for symbol in CONTRACT["symbols"]:
        for timeframe in CONTRACT["timeframes"]:
            write_json(root / "progress.json", {"status": "collecting", "symbol": symbol,
                       "timeframe": timeframe, "results_completed": len(cells)})
            dataset, frame = collect(symbol, timeframe, root)
            for strategy in STRATEGIES:
                signal = targets(frame, strategy)
                for profile, (fee, slip) in PROFILES.items():
                    result = run_canonical_target_exposure_backtest(dataset, signal,
                        BacktestConfig(initial_cash=500, fee_bps=fee, slippage_bps=slip),
                        registry_path=_registry_path(), start=WARMUP-1)
                    name = f"{symbol}-{timeframe}-{strategy}-{profile}"
                    result.fills.to_csv(root / (name+"-fills.csv"), index=False)
                    result.equity_curve.to_csv(root / (name+"-equity.csv"), index=False)
                    cells.append({"symbol": symbol, "timeframe": timeframe, "strategy": strategy,
                                  "profile": profile, "dataset_sha256": dataset["binding_sha256"],
                                  **summarize(result)})
            pd.DataFrame(cells).to_csv(root / "results.csv", index=False)
    report = {"contract": contract, "contract_sha256": digest(contract), "results": cells,
              "status": "historical_comparison_complete", "live_trading_authority": False,
              "automatic_paper_admission": False}
    write_json(root / "report.json", report)
    write_json(root / "progress.json", {"status": "complete", "results_completed": len(cells),
                                        "report_sha256": digest(report)})
    print(json.dumps({"status": "complete", "results": len(cells)}), flush=True)


if __name__ == "__main__":
    main()
