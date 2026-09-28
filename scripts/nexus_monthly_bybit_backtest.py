"""Public Bybit-only complete UTC calendar-month strategy matrix; research only.

No private keys, no Live, no owner Paper profile, no automatic Demo admissions.
Pages must form one exact, contiguous, strictly closed canonical market dataset.
"""
from __future__ import annotations

import argparse
import calendar
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest_engine import BacktestConfig
from bybit_public_klines import INTERVAL_MS, fetch_closed_klines
from canonical_backtest import run_canonical_target_exposure_backtest
from phase5_data_binding import validate_canonical_dataset
from phase6_research_pipeline import bind_bybit_closed_dataset, generate_targets, run_research_job
from product_research_runtime import COST_MODEL, KILL_CRITERIA, STRATEGY_PRESETS

CONTRACT = "nexus.bybit-calendar-month-pre-demo-research.v1"
PAIRS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
INTERVALS = {"15m": "15", "1h": "60", "4h": "240"}
MAX_PAGE = 500
INITIAL_RESEARCH_CASH = 10_000.0
SOURCE_RE = re.compile(r"^[0-9a-f]{40}$")


class MonthlyMatrixError(RuntimeError):
    pass


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def month_window(start: str, end_exclusive: str, now_ms: int) -> tuple[int, int]:
    try:
        a = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        b = datetime.strptime(end_exclusive, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise MonthlyMatrixError("month dates must be exact YYYY-MM-DD") from exc
    if a.day != 1 or b.day != 1:
        raise MonthlyMatrixError("require complete UTC calendar month boundaries")
    if (a.year, a.month) == (b.year, b.month) or (b.year * 12 + b.month) - (a.year * 12 + a.month) != 1:
        raise MonthlyMatrixError("exactly one contiguous calendar month required")
    if calendar.monthrange(a.year, a.month)[1] not in (28, 29, 30, 31):
        raise MonthlyMatrixError("invalid calendar month")
    lower = int(a.timestamp() * 1000)
    upper = int(b.timestamp() * 1000)
    if upper >= now_ms:
        raise MonthlyMatrixError("the complete calendar month must have fully closed")
    return lower, upper


def acquire_month(
    symbol: str,
    interval: str,
    start_ms: int,
    end_exclusive_ms: int,
    now_ms: int,
    *,
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_closed_klines,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if symbol not in PAIRS or interval not in INTERVAL_MS:
        raise MonthlyMatrixError("unapproved pair or timeframe")
    step = INTERVAL_MS[interval]
    if (start_ms % step or end_exclusive_ms % step or end_exclusive_ms <= start_ms
            or end_exclusive_ms > now_ms - step):
        raise MonthlyMatrixError("unclosed or off-grid monthly acquisition window")
    count = (end_exclusive_ms - start_ms) // step
    if count < 120 or count > 3_000:
        raise MonthlyMatrixError("monthly dataset count outside approved bounds")
    acquired: list[dict[str, Any]] = []
    page_receipts: list[dict[str, Any]] = []
    for start in range(start_ms, end_exclusive_ms, MAX_PAGE * step):
        page_end = min(start + (MAX_PAGE - 1) * step, end_exclusive_ms - step)
        expected = (page_end - start) // step + 1
        page = fetcher(symbol, interval, now_ms=now_ms,
                       start_time_ms=start, end_time_ms=page_end,
                       limit=expected, timeout_seconds=30.0)
        if len(page) != expected:
            raise MonthlyMatrixError("Bybit page incomplete: no silent candle substitution")
        times = [int(row["open_time_ms"]) for row in page]
        if times != list(range(start, page_end + step, step)):
            raise MonthlyMatrixError("Bybit page gaps, duplicates or off-grid timestamp")
        if any(row.get("source") != "Bybit" or row.get("market_type") != "spot"
               or row.get("symbol") != symbol or row.get("interval") != interval
               or row.get("closed") is not True or int(row["close_time_ms"]) >= now_ms
               for row in page):
            raise MonthlyMatrixError("Bybit page source namespace or candle finality invalid")
        page_receipts.append({"start_ms": start, "end_ms": page_end,
                              "rows": expected, "page_sha256": sha256(page)})
        acquired.extend(page)
    if len(acquired) != count or [int(r["open_time_ms"]) for r in acquired] != list(
        range(start_ms, end_exclusive_ms, step)
    ):
        raise MonthlyMatrixError("monthly collection is not one continuous candle window")
    dataset = bind_bybit_closed_dataset(
        acquired, canonical_symbol=symbol[:-4] + "/USDT",
        source_symbol=symbol, interval=interval,
    )
    validate_canonical_dataset(dataset)
    if dataset["row_count"] != count or dataset["source"] != "Bybit":
        raise MonthlyMatrixError("canonical month binding mismatch")
    return dataset, page_receipts


def closed_round_trips(fills: Any) -> dict[str, Any]:
    """Aggregate net PnL by complete long/flat exposure episode, not fill count."""
    quantity = cost = proceeds = 0.0
    wins = 0
    trades = 0
    positive = negative = 0.0
    for _, fill in fills.iterrows():
        change = float(fill["quantity_change"])
        notional = float(fill["notional"])
        fee = float(fill["fee"])
        if not all(math.isfinite(x) for x in (change, notional, fee)) or notional < 0 or fee < 0:
            raise MonthlyMatrixError("fill contains invalid financial values")
        if change > 0:
            quantity += change
            cost += notional + fee
        elif change < 0:
            quantity += change
            proceeds += notional - fee
            if quantity < -1e-7:
                raise MonthlyMatrixError("long-only backtest oversold an episode")
            if abs(quantity) < 1e-7:
                pnl = proceeds - cost
                trades += 1
                wins += pnl > 0
                positive += max(pnl, 0)
                negative += max(-pnl, 0)
                quantity = cost = proceeds = 0.0
    if abs(quantity) >= 1e-7:
        raise MonthlyMatrixError("end-of-month backtest left an unfinished trade")
    return {
        "closed_trades": trades,
        "win_rate_pct": None if not trades else round(100 * wins / trades, 4),
        "profit_factor": None if negative == 0 else round(positive / negative, 5),
        "profit_factor_note": "no losing closed trades" if negative == 0 and trades else
                              ("no trades" if trades == 0 else "computed"),
    }


def run_cell(dataset: dict[str, Any], symbol: str, timeframe: str, family: str, source_sha: str) -> dict[str, Any]:
    if family not in STRATEGY_PRESETS or timeframe not in INTERVALS:
        raise MonthlyMatrixError("unapproved strategy or timeframe")
    config = dict(STRATEGY_PRESETS[family])
    job = run_research_job(
        dataset,
        hypothesis="Pre-registered UTC calendar-month Bybit historical study; no profitability claim.",
        family=family,
        strategy_version=family + "-product-month-v1",
        strategy_config=config,
        code_sha=source_sha,
        cost_model=COST_MODEL,
        kill_criteria=KILL_CRITERIA,
    )
    targets = generate_targets(dataset, family, config)
    common = dict(initial_cash=INITIAL_RESEARCH_CASH, max_abs_exposure=1.0, liquidate_at_end=True)
    net = run_canonical_target_exposure_backtest(
        dataset, targets, BacktestConfig(**common, fee_bps=COST_MODEL["fee_bps"],
                                         slippage_bps=COST_MODEL["slippage_bps"]))
    zero_cost = run_canonical_target_exposure_backtest(
        dataset, targets, BacktestConfig(**common, fee_bps=0, slippage_bps=0))
    stress = run_canonical_target_exposure_backtest(
        dataset, targets, BacktestConfig(**common, fee_bps=COST_MODEL["stress_fee_bps"],
                                         slippage_bps=COST_MODEL["stress_slippage_bps"]))
    trip = closed_round_trips(net.fills)
    ev = job["evidence"]
    return {
        "symbol": symbol, "timeframe": timeframe, "strategy": family,
        "period": "one_full_utc_calendar_month", "bars": dataset["row_count"],
        "dataset_binding_sha256": dataset["binding_sha256"],
        "manifest_sha256": dataset["manifest_sha256"],
        "source_sha": source_sha, "fee_bps": COST_MODEL["fee_bps"],
        "slippage_bps": COST_MODEL["slippage_bps"],
        "initial_research_cash": INITIAL_RESEARCH_CASH,
        "gross_return_pct": round(100 * float(zero_cost.metrics["total_return"]), 4),
        "net_return_pct": round(100 * float(net.metrics["total_return"]), 4),
        "net_pnl_usdt": round(float(net.metrics["net_pnl"]), 4),
        "max_drawdown_pct": round(100 * float(net.metrics["max_drawdown"]), 4),
        "stress_net_return_pct": round(100 * float(stress.metrics["total_return"]), 4),
        "fill_count_not_trade_count": int(net.metrics["fill_count"]),
        "total_fees_usdt": round(float(net.metrics["total_fees"]), 4),
        **trip,
        "oos_score": ev.get("oos_score"),
        "walk_forward_score": ev.get("walk_forward_score"),
        "robustness_score": ev.get("robustness_score"),
        "qualification": job["qualification"]["status"],
        "research_only": True,
        "paper_only": True,
        "automatic_demo_promotion": False,
        "live_execution_allowed": False,
        "profitability_claim": False,
    }


def run_month(
    *, start: str, end_exclusive: str, output: Path, source_sha: str,
    now_ms: int | None = None,
    fetcher: Callable[..., list[dict[str, Any]]] = fetch_closed_klines,
) -> dict[str, Any]:
    if not SOURCE_RE.fullmatch(source_sha):
        raise MonthlyMatrixError("exact code SHA missing or invalid")
    now = int(time.time() * 1000) if now_ms is None else now_ms
    a, b = month_window(start, end_exclusive, now)
    if output.exists():
        raise MonthlyMatrixError("monthly evidence output must be a new destination")
    output.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    acquisitions: list[dict[str, Any]] = []
    with (output / "cells.jsonl").open("w", encoding="utf-8") as journal:
        for pair in PAIRS:
            for tf, interval in INTERVALS.items():
                dataset, pages = acquire_month(pair, interval, a, b, now, fetcher=fetcher)
                dataset_file = output / "datasets" / f"{pair}-{tf}.json"
                dataset_file.parent.mkdir(parents=True, exist_ok=True)
                dataset_file.write_bytes(canonical_json(dataset))
                acquisitions.append({
                    "symbol": pair, "timeframe": tf, "rows": dataset["row_count"],
                    "dataset_sha256": hashlib.sha256(dataset_file.read_bytes()).hexdigest(),
                    "binding_sha256": dataset["binding_sha256"], "pages": pages,
                })
                for family in STRATEGY_PRESETS:
                    row = run_cell(dataset, pair, tf, family, source_sha)
                    rows.append(row)
                    journal.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                    journal.flush()
    if len(rows) != len(PAIRS) * len(INTERVALS) * len(STRATEGY_PRESETS):
        raise MonthlyMatrixError("full-month matrix is incomplete")
    fieldnames = list(rows[0])
    with (output / "review-table.csv").open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "contract_version": CONTRACT, "decision": "FULL_MONTH_HISTORICAL_BACKTEST_COMPLETE",
        "start_utc": start, "end_exclusive_utc": end_exclusive, "code_sha": source_sha,
        "bybit_only": True, "exact_canonical_months": len(acquisitions),
        "strategy_cells": len(rows), "no_demo_or_live_execution": True,
        "owner_review_required_before_any_new_demo": True,
        "no_profitability_claim": True, "acquisitions": acquisitions,
        "report_sha256": hashlib.sha256((output / "review-table.csv").read_bytes()).hexdigest(),
    }
    (output / "summary.json").write_bytes(canonical_json(summary))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="inclusive UTC month first, YYYY-MM-DD")
    parser.add_argument("--end-exclusive", required=True, help="next UTC month first, YYYY-MM-DD")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = run_month(
            start=args.start, end_exclusive=args.end_exclusive,
            output=args.output,
            source_sha=os.environ.get("NEXUS_SOURCE_SHA", ""),
        )
    except Exception as exc:
        print("MONTHLY_MATRIX_FAIL_CLOSED: " + type(exc).__name__ + ": " + str(exc)[:220], file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps({key: summary[key] for key in (
        "decision", "start_utc", "end_exclusive_utc", "code_sha",
        "exact_canonical_months", "strategy_cells",
        "owner_review_required_before_any_new_demo",
    )}, sort_keys=True))


if __name__ == "__main__":
    main()
