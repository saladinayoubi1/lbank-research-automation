"""Frozen portfolio consumer: original engine, separate numerical QA, no dispatch.

Both public operations reject an incomplete horizon before opening any input.
The QA entry point never calls the original signal or execution implementation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as engine
from scripts import nexus_portfolio_v3_forward_raw_source as source
from scripts import nexus_portfolio_v3_warmup_context as context

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "research/portfolio_v3_forward_executor_v1.json"
CONTRACT_DIGEST = "996a80846faf37fb5d1e6fa307ad1d92ca0e878cf863b1556dc9e7b56f66a5dd"
INDEPENDENT = "research/portfolio_v3_forward_independent_qa.py"
PERIOD = {"start": "2026-10-19", "end": "2027-01-17"}
SCHEMA = "nexus.portfolio-v3-fixed-forward-execution.v1"
QA_SCHEMA = "nexus.portfolio-v3-fixed-forward-independent-qa.v1"
FLAGS = {"research_only": True, "financial_dispatch_authorized": False,
         "economic_edge_established": False, "paper_eligible": False,
         "live_enabled": False, "orders": 0,
         "independent_worker_lease_verified": False}
RESULT_FIELDS = {"schema", "contract_digest", "producer_sha256_lf",
                 "independent_qa_sha256_lf", "source_bindings", "market_digest",
                 "candidate_id", "period", "cost_profiles", "books", "targets",
                 "review_mask", "cells", "strategy_backtest_performed",
                 "independent_financial_qa_complete", "digest", *FLAGS}


class ForwardExecutorError(ValueError):
    pass


def checked_contract(root=ROOT):
    plan = source.read_json(root / CONTRACT, 32768)
    if source.digest(plan) != CONTRACT_DIGEST:
        raise ForwardExecutorError("Fixed forward executor contract changed")
    for name, expected in plan["code_and_contract_sha256_lf"].items():
        if source.sha_file(root / name, lf=True) != expected:
            raise ForwardExecutorError("Reviewed executable or contract changed: " + name)
    modules = ((engine, "bybit_portfolio_search_v3.py"),
               (context, "scripts/nexus_portfolio_v3_warmup_context.py"),
               (source, "scripts/nexus_portfolio_v3_forward_raw_source.py"))
    for module, name in modules:
        if source.sha_file(Path(module.__file__), lf=True) != plan["code_and_contract_sha256_lf"][name]:
            raise ForwardExecutorError("Loaded implementation differs from reviewed file")
    _, spec = context.checked_contract(root)
    source.checked_policy(root)
    return plan, spec


def historical_context(context_root, archive_root, plan):
    report = source.checked_digest(context_root / "context.json")
    if (report["digest"] != plan["historical_context_digest"]
            or report.get("schema") != "nexus.portfolio-v3-verified-warmup-context.v1"
            or report.get("strategy_backtest_performed") is not False
            or report.get("financial_dispatch_authorized") is not False):
        raise ForwardExecutorError("Historical context is not the approved sealed preparation")
    original = report["source_bindings"]["original_archive_six_sha256"]
    if original != source.independent.ORIGINAL_SHA256:
        raise ForwardExecutorError("Original archive identity set changed")
    for name, expected in original.items():
        if source.sha_file(archive_root / name, 20_000_000) != expected:
            raise ForwardExecutorError("Original six-file source changed")
    market = context.load_market_bundle(context_root / "joined-market-4h.npz",
                                        report["joined_market_bundle_sha256"])
    return market, {"historical_context_digest": report["digest"],
                    "historical_bundle_sha256": report["joined_market_bundle_sha256"],
                    "original_archive_six_sha256_rechecked": original}


def future_source(capture_root, qa_path, plan):
    now = source.closed_horizon()
    qa = source.checked_digest(qa_path)
    identity = source.request_identity()
    required = {"schema": "nexus.portfolio-v3-forward-official-raw-independent-qa.v1",
                "policy_digest": source.POLICY_DIGEST,
                "collector_and_qa_wrapper_sha256_lf": identity["collector_sha256_lf"],
                "independent_decimal_code_sha256_lf": source.sha_file(Path(source.independent.__file__), lf=True),
                "candidate_id": plan["candidate_id"], "source_route": identity["source_route"],
                "start_utc": identity["start_utc"], "end_exclusive_utc": identity["end_exclusive_utc"]}
    if any(qa.get(k) != v for k, v in required.items()):
        raise ForwardExecutorError("Future source QA identity changed")
    for key, expected in {"verified_files": 180, "verified_4h_bars_per_asset": 540, "orders": 0}.items():
        if type(qa.get(key)) is not int or qa[key] != expected:
            raise ForwardExecutorError("Incomplete future source counts")
    for key, expected in {
        "all_ticks_independently_reconstructed": True,
        "source_eligible_for_separate_research_handoff": True,
        "provider_payload_exchange_signed": False, "external_host_attestation_verified": False,
        "financial_executor_handoff_still_required": True,
        "strategy_backtest_performed": False, "financial_dispatch_authorized": False,
        "ready_for_strategy_result_or_paper": False, "paper_eligible": False, "live_enabled": False,
    }.items():
        if qa.get(key) is not expected:
            raise ForwardExecutorError("Substituted source authority or incomplete QA")
    if source.read_json(capture_root / "capture-request.json", 16384) != identity:
        raise ForwardExecutorError("Future capture request changed")
    summary = source.checked_digest(capture_root / "capture-summary.json")
    if (qa.get("capture_digest") != summary["digest"]
            or summary.get("files") != qa.get("files")
            or any(summary.get(k) != v for k, v in identity.items())
            or summary.get("request_digest") != source.digest(identity)
            or summary.get("completed_files") != 180
            or summary.get("independent_full_tick_qa_complete") is not False
            or summary.get("provider_payload_exchange_signed") is not False
            or summary.get("external_host_attestation_verified") is not False
            or [(r["symbol"], r["date"]) for r in summary.get("files", [])] != list(source.jobs())):
        raise ForwardExecutorError("Future capture and independent QA are detached")
    bars = qa.get("bars")
    if (type(bars) is not dict or set(bars) != set(source.SYMBOLS)
            or any(type(v) is not list or len(v) != 540 for v in bars.values())):
        raise ForwardExecutorError("Full paired source coverage required")
    position = {s: 0 for s in source.SYMBOLS}
    total = trades = 0
    for item, (symbol, day) in zip(summary["files"], source.jobs(), strict=True):
        cell, expected_item = source.check_cell(capture_root, symbol, day, identity, now)
        if item != expected_item or len(cell["fully_observed_4h_bars"]) != 6:
            raise ForwardExecutorError("Future raw day or acquisition receipt changed")
        midnight = datetime.fromisoformat(day + "T00:00:00+00:00")
        for k, produced in enumerate(cell["fully_observed_4h_bars"]):
            bar = bars[symbol][position[symbol]]
            position[symbol] += 1
            if (set(bar) != {"timestamp", *context.PRICE_KEYS, "volume", "raw_file_sha256", "receipt_sha256"}
                    or source.stamp(bar["timestamp"]) != midnight + timedelta(hours=4 * k)
                    or source.stamp(produced["timestamp"]) != source.stamp(bar["timestamp"])
                    or bar["raw_file_sha256"] != item["raw_file_sha256"]
                    or bar["receipt_sha256"] != item["receipt_sha256"]):
                raise ForwardExecutorError("Independent bar detached from its raw day")
            for field in (*context.PRICE_KEYS, "volume"):
                if type(bar[field]) is not str:
                    raise ForwardExecutorError("Independent Decimal source representation required")
                a, b = Decimal(bar[field]), Decimal(str(produced[field]))
                limit = max(Decimal("0.000001"), abs(a) * Decimal("1e-10")) if field == "volume" else Decimal("1e-8")
                if not a.is_finite() or not b.is_finite() or a <= 0 or b <= 0 or abs(a-b) > limit:
                    raise ForwardExecutorError("Independent future OHLCV differs from retained source")
        total += item["raw_gzip_bytes"]
        trades += item["raw_trade_rows"]
        if total > source.MAX_TOTAL:
            raise ForwardExecutorError("Future raw source byte budget exceeded")
    if any(obj.get("raw_gzip_bytes") != total or obj.get("raw_trade_rows") != trades for obj in (qa, summary)):
        raise ForwardExecutorError("Future source totals changed")
    return bars, {"future_source_qa_digest": qa["digest"], "future_capture_digest": summary["digest"],
                  "future_daily_files_rehashed": 180, "future_raw_trade_rows": trades,
                  "future_source_route": identity["source_route"],
                  "provider_payload_exchange_signed": False, "external_host_attestation_verified": False}


def join_future(historical, bars):
    context.validate_market(historical, context.CUTOFF)
    times = pd.date_range(source.START, source.END, freq="4h", inclusive="left")
    columns = {}
    for symbol in source.SYMBOLS:
        rows = bars[symbol]
        if (len(rows) != 540 or any(source.stamp(row["timestamp"]) != t.to_pydatetime()
                                   for row, t in zip(rows, times, strict=True))):
            raise ForwardExecutorError("Future source has a missing/shifted UTC candle")
        columns[symbol] = rows
    market = {"symbols": list(context.SYMBOLS), "timestamps": pd.concat([
        historical["timestamps"], pd.Series(times)], ignore_index=True)}
    for field in context.PRICE_KEYS:
        tail = np.column_stack([[float(row[field]) for row in columns[s]] for s in source.SYMBOLS])
        market[field] = np.vstack([historical[field], tail])
    context.validate_market(market, pd.Timestamp(source.END))
    if len(market["timestamps"]) != 9048:
        raise ForwardExecutorError("Original grid plus complete future horizon required")
    return market


def load_inputs(context_root, archive_root, capture_root, source_qa_path, plan):
    source.closed_horizon()
    historical, old_binding = historical_context(context_root, archive_root, plan)
    bars, new_binding = future_source(capture_root, source_qa_path, plan)
    market = join_future(historical, bars)
    return market, {**old_binding, **new_binding}


def market_digest(market):
    return source.digest({"timestamps_ns": market["timestamps"].astype("int64").tolist(),
                          "symbols": market["symbols"],
                          **{k: context.array_digest(market[k]) for k in context.PRICE_KEYS}})


def book_target(book, original):
    if book in ("existing_dual_rotation_unmodified", "existing_dual_rotation_dd20"):
        return original, True, book.endswith("_dd20")
    fixed = {"passive_BTC_Spot": (1., 0.), "passive_ETH_Spot": (0., 1.),
             "passive_50_50_BTC_ETH": (.5, .5), "cash_only": (0., 0.)}
    if book not in fixed:
        raise ForwardExecutorError("Unreviewed portfolio book")
    return np.tile(fixed[book], (len(original), 1)), False, False


def _new_output(path):
    path = source.unlinked(path)
    if path.exists():
        raise ForwardExecutorError("New write-once result path required")
    return path


def run(context_root, archive_root, capture_root, source_qa_path, output, *, root=ROOT):
    source.closed_horizon()
    plan, spec = checked_contract(root)
    output = _new_output(output)
    market, bindings = load_inputs(context_root, archive_root, capture_root, source_qa_path, plan)
    state = engine.build_structural_state(market, spec["candidate"])
    vol = engine.realized_vol(market["close"], spec["candidate"]["params"]["vol_days"])
    weights = engine.construct_weights(state, vol, spec["candidate"])
    mask = engine._candidate_rebalance_mask(len(weights), spec["candidate"])
    cells = {}
    for label, profile in spec["cost_profiles"].items():
        cells[label] = {}
        for book in spec["comparators"]:
            target, scheduled, guarded = book_target(book, weights)
            trace = {}
            metrics = engine.exact_backtest(market, target, PERIOD, profile,
                rebalance_mask=mask if scheduled else None, fill_trace=trace,
                risk_policy=spec["risk_comparisons"]["fixed_posthoc_dd20"] if guarded else None)
            cells[label][book] = {"metrics": metrics, "trace": trace}
    checked_contract(root)
    result = {"schema": SCHEMA, "contract_digest": CONTRACT_DIGEST,
              "producer_sha256_lf": source.sha_file(Path(__file__), lf=True),
              "independent_qa_sha256_lf": plan["code_and_contract_sha256_lf"][INDEPENDENT],
              "source_bindings": bindings, "market_digest": market_digest(market),
              "candidate_id": plan["candidate_id"], "period": PERIOD,
              "cost_profiles": spec["cost_profiles"], "books": spec["comparators"],
              "targets": weights.tolist(), "review_mask": mask.tolist(), "cells": cells,
              "strategy_backtest_performed": True, "independent_financial_qa_complete": False,
              **FLAGS}
    result["digest"] = source.digest(result)
    source.write_once(output, result)
    return result


def verify(context_root, archive_root, capture_root, source_qa_path, receipt_path, output, *, root=ROOT):
    source.closed_horizon()
    plan, spec = checked_contract(root)
    output = _new_output(output)
    receipt = source.checked_digest(receipt_path, 12_000_000)
    expected = {"schema": SCHEMA, "contract_digest": CONTRACT_DIGEST,
                "producer_sha256_lf": source.sha_file(Path(__file__), lf=True),
                "independent_qa_sha256_lf": plan["code_and_contract_sha256_lf"][INDEPENDENT],
                "candidate_id": plan["candidate_id"], "period": PERIOD,
                "cost_profiles": spec["cost_profiles"], "books": spec["comparators"],
                "strategy_backtest_performed": True, "independent_financial_qa_complete": False,
                **FLAGS}
    if (set(receipt) != RESULT_FIELDS or any(receipt.get(k) != v for k, v in expected.items())
            or any(receipt.get(k) is not v for k, v in {**FLAGS, "strategy_backtest_performed": True,
                                                       "independent_financial_qa_complete": False}.items() if type(v) is bool)
            or type(receipt.get("orders")) is not int):
        raise ForwardExecutorError("Altered producer, execution contract or authority")
    market, bindings = load_inputs(context_root, archive_root, capture_root, source_qa_path, plan)
    if receipt["source_bindings"] != bindings or receipt["market_digest"] != market_digest(market):
        raise ForwardExecutorError("Execution detached from canonical source inputs")
    from research import portfolio_v3_forward_independent_qa as independent
    if source.sha_file(Path(independent.__file__), lf=True) != expected["independent_qa_sha256_lf"]:
        raise ForwardExecutorError("Loaded independent verifier differs from reviewed code")
    reference = independent.reference_weights(market)
    if (type(receipt["targets"]) is not list or len(receipt["targets"]) != len(reference)
            or any(type(row) is not list or len(row) != 2
                   or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in row)
                   for row in receipt["targets"])):
        raise ForwardExecutorError("Targets must be finite typed numeric pairs, not coercible JSON values")
    actual = np.asarray(receipt["targets"], dtype=float)
    review = (np.arange(len(reference)) % 42 == 0)
    if (actual.shape != reference.shape or not np.array_equal(actual, reference)
            or type(receipt["review_mask"]) is not list
            or any(type(v) is not bool for v in receipt["review_mask"])
            or not np.array_equal(receipt["review_mask"], review)):
        raise ForwardExecutorError("Independent source signal or global review phase differs")
    cells = receipt["cells"]
    if (type(cells) is not dict or set(cells) != set(spec["cost_profiles"])
            or any(type(rows) is not dict or set(rows) != set(spec["comparators"]) for rows in cells.values())):
        raise ForwardExecutorError("Complete fixed six-book/three-cost matrix required")
    checked = {}
    for label, profile in spec["cost_profiles"].items():
        checked[label] = {}
        for book in spec["comparators"]:
            row = cells[label][book]
            if type(row) is not dict or set(row) != {"trace", "metrics"}:
                raise ForwardExecutorError("Unexpected execution cell")
            target, scheduled, guarded = book_target(book, reference)
            checked[label][book] = independent.audit_cell(market, target, row["trace"],
                row["metrics"], profile, scheduled=scheduled, guarded=guarded)
    checked_contract(root)
    result = {"schema": QA_SCHEMA, "producer_receipt_digest": receipt["digest"],
              "contract_digest": CONTRACT_DIGEST, "source_bindings": bindings,
              "market_digest": receipt["market_digest"], "independent_signal_qa_complete": True,
              "independent_financial_qa_complete": True, "cells_checked": 18, "cells": checked,
              "economic_interpretation": "FIXED_90_DAY_FALSIFICATION_REVIEW_ONLY_NOT_EDGE_PROOF",
              "no_arbitrary_minimum_trade_count": True, **FLAGS}
    result["digest"] = source.digest(result)
    source.write_once(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "run", "qa"))
    for name in ("context-root", "archive-root", "capture-root", "source-qa", "receipt", "output"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.action == "status":
        result = {"full_horizon_elapsed": source.now_utc() >= source.END,
                  "end_exclusive_utc": "2027-01-17T00:00:00Z", "source_prices_read": False,
                  "financial_result_ready": False, **FLAGS}
    else:
        names = ("context_root", "archive_root", "capture_root", "source_qa", "output")
        if any(getattr(args, name) is None for name in names) or (args.action == "qa" and args.receipt is None):
            parser.error("Context, archive, capture, source QA and new output paths are required; qa also needs receipt")
        inputs = (args.context_root, args.archive_root, args.capture_root, args.source_qa)
        result = run(*inputs, args.output) if args.action == "run" else verify(*inputs, args.receipt, args.output)
    print(json.dumps({k: v for k, v in result.items() if k not in ("cells", "targets", "review_mask")},
                     sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
