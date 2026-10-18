"""Independent audit of V119's recorded fills against pinned historical bars.

Never imports the research engine, generates signals, selects trades or reruns
the backtest. Only the previously recorded paths and their accounting are checked.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
from pathlib import Path

LEDGER_SHA256 = "46be9c744f14d73d0be391f3b164d127ef93e5bcc80f701225b34ab8838e2546"
RESULT_DIGEST = "bd27b37d66caabfd79e7d19ad158bdf665e0efce51772167e98ea05957f90fb8"
ENGINE_SHA256 = "c19d49e644fe0067e405b5cc25366f54b33d403c5445bd9dd56d7210c9de1672"
SOURCE_SHAS = {
    "BTC": "c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETH": "ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
PARTS = ("training", "validation_already_inspected", "historical_test_already_inspected")
PROFILES = {"conservative": ("0.001", "0.0005"), "stress": ("0.0025", "0.0015")}
TOLERANCE = Decimal("0.000001")  # Original ledger publishes eight decimal places.


class AccountingAuditError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def dec(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise AccountingAuditError("nonfinite ledger/source value")
    return result


def require(condition, message):
    if not condition:
        raise AccountingAuditError(message)


def equal(actual, expected, message):
    require(abs(dec(actual) - dec(expected)) <= TOLERANCE, message)


def fixed_trade_exit(frame, trade, partition_end):
    """First physical exit for ONE recorded position; no candidate generation."""
    entry = trade["entry_index"]
    stop, target = dec(trade["structural_stop"]), dec(trade["structural_target"])
    for index in range(entry, min(entry + 96, partition_end - 1) + 1):
        bar = frame.iloc[index]
        opened, low, high = (dec(bar[k]) for k in ("open", "low", "high"))
        if index in (entry + 96, partition_end - 1):
            return index, opened, "TIMEOUT_OR_PARTITION_END_OPEN"
        if low <= stop:
            cause = ("STRUCTURE_STOP_GAP" if opened < stop else
                     "STOP_FIRST_AMBIGUOUS" if high >= target else "STRUCTURE_STOP_ONLY")
            return index, min(opened, stop), cause
        if high >= target:
            return index, target, "PRECOMMITTED_TARGET"
    raise AccountingAuditError("recorded position has no physical closure")


def audit_recorded_paths(ledger, frames):
    n = 128544
    bounds = ((64, int(n * .60)), (int(n * .60), int(n * .80)), (int(n * .80), n))
    rows = []
    for part, (start, end) in zip(PARTS, bounds):
        result = ledger["results"][part]
        require(result["start_utc"] == frames["BTC"].iloc[start]["timestamp"].isoformat()
                and result["end_utc"] == frames["BTC"].iloc[end - 1]["timestamp"].isoformat(),
                "recorded partition timestamp mismatch")
        for profile, (fee_text, slip_text) in PROFILES.items():
            recorded = result["profiles"][profile]
            fee, slip = dec(fee_text), dec(slip_text)
            cash = peak = dec(500)
            worst_drawdown = gross_total = fees_total = slip_total = dec(0)
            next_available = start
            counts, months = Counter(), defaultdict(list)
            trades = recorded["trades"]
            for trade in trades:
                entry, exit_index = trade["entry_index"], trade["exit_index"]
                require(type(entry) is int and type(exit_index) is int
                        and next_available <= entry <= exit_index < end,
                        "overlap or partition escape in shared cash book")
                symbol = trade["symbol"]
                require(symbol in SOURCE_SHAS, "unexpected traded asset")
                frame = frames[symbol]
                mid = dec(frame.iloc[entry]["open"])
                equal(mid, trade["entry_mid"], "entry is not physical bar open")
                fill = mid * (1 + slip)
                equal(fill, trade["entry_fill"], "adverse entry slippage mismatch")
                stop, target = dec(trade["structural_stop"]), dec(trade["structural_target"])
                require(0 < stop < mid < target and fill < target
                        and (target - mid) / (mid - stop) >= dec("1.49999999"),
                        "recorded bracket or minimum reward/risk mismatch")
                unit_spend = fill * (1 + fee)
                unit_risk = unit_spend - stop * (1 - slip) * (1 - fee)
                quantity = dec(trade["qty"])
                expected_quantity = (min(dec(250) / fill, dec("2.5") / unit_risk,
                                         cash / unit_spend) * dec("1e8")).to_integral_value(
                                             rounding=ROUND_FLOOR) / dec("1e8")
                require(quantity > 0 and abs(quantity - expected_quantity) <= dec("1e-8"),
                        "recorded sizing differs from fixed cash/risk/notional budget")
                require(quantity * fill <= dec(250) + TOLERANCE
                        and quantity * unit_risk <= dec("2.5") + TOLERANCE,
                        "notional or nominal gapless risk cap exceeded")
                spend = quantity * unit_spend
                require(spend <= cash + TOLERANCE, "shared cash overspent")
                equal(spend, trade["entry_cash_spend_usdt"], "entry cash debit mismatch")
                physical_index, reference, cause = fixed_trade_exit(frame, trade, end)
                require((physical_index, cause) == (exit_index, trade["cause"]),
                        "recorded exit is not first physical bracket/timeout exit")
                exit_time = frame.iloc[exit_index]["timestamp"].isoformat()
                require(exit_time == trade["exit_utc"], "exit source bar timestamp mismatch")
                proceeds = quantity * reference * (1 - slip) * (1 - fee)
                net = proceeds - spend
                gross = quantity * (reference - mid)
                fees = quantity * (fill + reference * (1 - slip)) * fee
                slippage = quantity * (fill - mid + reference * slip)
                equal(proceeds, trade["exit_cash_proceeds_usdt"], "exit cash credit mismatch")
                equal(net, trade["net_pnl_usdt"], "net trade PnL mismatch")
                equal(gross - fees - slippage, net, "gross minus friction does not equal net")
                cash += net
                peak = max(peak, cash)
                worst_drawdown = max(worst_drawdown, (peak - cash) / peak * 100)
                gross_total += gross
                fees_total += fees
                slip_total += slippage
                counts[cause] += 1
                months[exit_time[:7]].append(net)
                next_available = exit_index + 1
            require(len(trades) == recorded["round_trips"], "closed trade count mismatch")
            require(sum(t["net_pnl_usdt"] > 0 for t in trades) == recorded["positive_net_trades"],
                    "positive trade count mismatch")
            equal(recorded["initial_shared_cash_usdt"], 500, "reference capital changed")
            equal(cash, recorded["ending_cash_usdt"], "ending cash reconciliation failed")
            equal(cash - 500, recorded["net_pnl_usdt"], "partition net reconciliation failed")
            equal((cash - 500) / len(trades), recorded["mean_pnl_usdt"], "trade mean mismatch")
            require([m["month"] for m in recorded["monthly"]] == sorted(months),
                    "monthly coverage mismatch")
            for month in recorded["monthly"]:
                values = months[month["month"]]
                require(len(values) == month["round_trips"], "monthly trade count mismatch")
                equal(sum(values), month["net_pnl_usdt"], "monthly net mismatch")
                equal(sum(values) / len(values), month["mean_pnl_usdt"], "monthly mean mismatch")
            rows.append({
                "part": part, "profile": profile, "round_trips": len(trades),
                "initial_shared_cash_usdt": 500, "ending_cash_usdt": round(float(cash), 8),
                "gross_pnl_usdt": round(float(gross_total), 8),
                "fees_usdt": round(float(fees_total), 8),
                "slippage_usdt": round(float(slip_total), 8),
                "net_pnl_usdt": recorded["net_pnl_usdt"],
                "mean_pnl_usdt": recorded["mean_pnl_usdt"],
                "net_return_pct": round(float((cash - 500) / 5), 8),
                "max_closed_cash_drawdown_pct": round(float(worst_drawdown), 8),
                "max_equity_drawdown_pct": None,
                "monthly_rows_checked": len(months), "exit_causes": dict(sorted(counts.items())),
            })
    return rows


def run_audit(ledger_path: Path, market_root: Path, engine_path: Path):
    # Dataframe dependency is restricted to this offline QA command, never the UI.
    import pandas as pd

    require(hashlib.sha256(ledger_path.read_bytes()).hexdigest() == LEDGER_SHA256,
            "original ledger byte SHA256 mismatch")
    require(hashlib.sha256(engine_path.read_bytes()).hexdigest() == ENGINE_SHA256,
            "frozen research implementation changed")
    ledger = json.loads(ledger_path.read_bytes())
    require(ledger["result_digest"] == RESULT_DIGEST
            and digest({k: v for k, v in ledger.items() if k != "result_digest"}) == RESULT_DIGEST,
            "original research result digest mismatch")
    frames = {}
    for symbol, expected in SOURCE_SHAS.items():
        path = market_root / (symbol.lower() + "_usdt") / "minute15.parquet"
        require(hashlib.sha256(path.read_bytes()).hexdigest() == expected,
                "physical source SHA256 mismatch: " + symbol)
        frame = pd.read_parquet(path)
        require(len(frame) == 128544 and set(frame.columns) == {
            "timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"},
            "physical source schema/row count mismatch")
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        require(frame["timestamp"].is_monotonic_increasing
                and (frame["timestamp"].diff().iloc[1:] == pd.Timedelta(minutes=15)).all()
                and (frame["symbol"] == symbol.lower() + "_usdt").all()
                and (frame["timeframe"] == "minute15").all(), "physical source grid/identity mismatch")
        require(frame.iloc[0]["timestamp"].isoformat() == ledger["source_start_utc"]
                and frame.iloc[-1]["timestamp"].isoformat() == ledger["source_end_utc"],
                "physical source range mismatch")
        frames[symbol] = frame
    require(frames["BTC"]["timestamp"].equals(frames["ETH"]["timestamp"]), "peer grid mismatch")
    rows = audit_recorded_paths(ledger, frames)
    core = {
        "schema": "nexus.elliott-v119-fixed-recorded-path-accounting-qa.v1",
        "passed": True, "ledger_raw_sha256": LEDGER_SHA256, "result_digest": RESULT_DIGEST,
        "engine_raw_sha256": ENGINE_SHA256, "source_shas": SOURCE_SHAS,
        "source_bars_per_asset_checked": 128544, "partition_cost_cells_checked": len(rows),
        "recorded_trade_rows_checked": sum(row["round_trips"] for row in rows),
        "unique_recorded_trade_paths": 77,
        "monthly_rows_checked": sum(row["monthly_rows_checked"] for row in rows),
        "absolute_usdt_tolerance": str(TOLERANCE), "rows": rows,
        "fixed_recorded_trade_paths_checked": True,
        "signal_generation_replayed": False, "backtest_reexecuted": False,
        "signal_to_entry_causality_independently_verified": False,
        "structural_pivot_identity_independently_verified": False,
        "full_elliott_wave_count_verified": False,
        "exit_utc_semantics": "source_bar_open_timestamp_not_exact_intrabar_fill_time",
        "independent_future_holdout": False, "paper_eligible": False,
        "automatic_demo_promotion": False, "live_enabled": False, "orders": 0,
        "disposition": "HISTORICAL_NEGATIVE_DO_NOT_RETUNE",
    }
    return {**core, "qa_digest": digest(core)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--market-root", required=True, type=Path)
    parser.add_argument("--engine", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    require(args.output.resolve() not in {args.ledger.resolve(), args.engine.resolve()},
            "audit output cannot overwrite frozen evidence/code")
    result = run_audit(args.ledger, args.market_root, args.engine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n",
                           encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, sort_keys=True))


if __name__ == "__main__":
    main()
