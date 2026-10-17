"""Independent, immutable-accounting triage for the FIRST source-bound Butterfly V8.

This is NOT a strategy finder, physical source audit, new backtest or order
adapter. It cannot qualify a candidate or turn a training profit into Demo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping

EXPECTED_REPORT_DIGEST = "21be76c6f276c0d71ed4f87a2a045eee7ee9050d4d789ee1a862be8ad333c4c0"
EXPECTED_SOURCE_SHA = "2b89f6e89abdacc16b3288b9fd9ebcb3bdea7e69"
EXPECTED_ARCHIVE_SHA = "2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"
EXPECTED_CONTRACT_FINGERPRINT = "c451551fdb8bacd867e865eb494a14ba506061cbffd9542aca04e13df3f56f02"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
PARTS = ("train", "validation", "historically_inspected_test")
PROFILES = ("conservative", "stress")
SCHEMA = "nexus.causal-butterfly-v8-independent-cost-audit.v1"


class ButterflyCostAuditError(ValueError):
    pass


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ButterflyCostAuditError("source report missing, linked or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ButterflyCostAuditError("Butterfly report not readable") from exc
    if not isinstance(value, dict):
        raise ButterflyCostAuditError("Butterfly report must be an object")
    return value


def audit(report: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(report, Mapping):
        raise ButterflyCostAuditError("invalid report")
    core = dict(report)
    signature = core.pop("report_digest", None)
    if (
        signature != EXPECTED_REPORT_DIGEST or signature != _digest(core)
        or report.get("schema") != "nexus.automatic-composite-research.v1"
        or report.get("source_sha") != EXPECTED_SOURCE_SHA
        or report.get("archive_sha256") != EXPECTED_ARCHIVE_SHA
        or report.get("qualification") != "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
        or report.get("research_only") is not True
        or report.get("live_enabled") is not False
        or report.get("auto_demo_promotion") is not False
        or report.get("historical_test_pristine") is not False
        or report.get("independent_future_data_required") is not True
    ):
        raise ButterflyCostAuditError("unverified Butterfly source/report/authority")
    ranking = report.get("frontier_screening")
    if (
        not isinstance(ranking, dict)
        or ranking.get("selected_mechanism") != "factory_causal_bullish_butterfly"
        or ranking.get("candidate_count") != 1
        or ranking.get("validation_used_for_selection") is not False
        or ranking.get("historically_inspected_test_used_for_selection") is not False
    ):
        raise ButterflyCostAuditError("source-selected Butterfly frontier changed")
    rows = report.get("rows")
    if not isinstance(rows, list) or len(rows) != 12:
        raise ButterflyCostAuditError("full two-symbol/split/cost denominator missing")

    cells: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ButterflyCostAuditError("malformed numeric cell")
        key = (row.get("symbol"), row.get("part"), row.get("profile"))
        if (
            key not in {(s, p, c) for s in SYMBOLS for p in PARTS for c in PROFILES}
            or key in cells
            or row.get("mechanism") != "factory_causal_bullish_butterfly"
            or row.get("config_fingerprint") != EXPECTED_CONTRACT_FINGERPRINT
        ):
            raise ButterflyCostAuditError("wrong or duplicate Butterfly numeric cell")
        trades = row.get("closed_round_trips")
        pnl = row.get("net_pnl_usdt")
        roi = row.get("net_return_pct")
        if (type(trades) is not int or trades < 0
                or type(pnl) not in (int, float) or not math.isfinite(pnl)
                or type(roi) not in (int, float) or not math.isfinite(roi)
                or abs(pnl / 10000.0 * 100.0 - roi) > 1e-5
                or (trades == 0 and (pnl != 0 or roi != 0))):
            raise ButterflyCostAuditError("unreconcilable trade/PnL/equity cell")
        cells[key] = row
    if len(cells) != 12:
        raise ButterflyCostAuditError("missing fixed split/symbol/cost cell")

    # Fixed acceptance test on the ORIGINAL screen, not a request to retune
    # the historical splits. Training positive after 15 bps/side has no
    # independent qualification when both 40 bps/side stress returns lose.
    def cell(s: str, p: str, c: str) -> dict[str, Any]:
        return cells[(s, p, c)]

    training_cost_fragile = all(
        cell(s, "train", "conservative")["net_pnl_usdt"] > 0
        and cell(s, "train", "stress")["net_pnl_usdt"] < 0 for s in SYMBOLS
    )
    validation_negative = all(
        cell(s, "validation", cost)["net_pnl_usdt"] < 0
        for s in SYMBOLS for cost in PROFILES
    )
    inspected_test_inactive = all(
        cell(s, "historically_inspected_test", cost)["closed_round_trips"] == 0
        for s in SYMBOLS for cost in PROFILES
    )
    if not (training_cost_fragile and validation_negative and inspected_test_inactive):
        raise ButterflyCostAuditError("unexpected changed economics needs independent review")

    per_symbol: list[dict[str, Any]] = []
    for s in SYMBOLS:
        profile_rows = [{
            "partition": p, "cost_profile": cost,
            "closed_round_trips": cell(s, p, cost)["closed_round_trips"],
            "net_pnl_usdt": cell(s, p, cost)["net_pnl_usdt"],
        } for p in PARTS for cost in PROFILES]
        per_symbol.append({"symbol": s, "cells": profile_rows})
    totals = [{
        "partition": p, "cost_profile": cost,
        "sum_independent_account_pnl_usdt": round(
            sum(cell(s, p, cost)["net_pnl_usdt"] for s in SYMBOLS), 8,
        ),
        "total_closed_round_trips": sum(
            cell(s, p, cost)["closed_round_trips"] for s in SYMBOLS
        ),
    } for p in PARTS for cost in PROFILES]
    unsigned = {
        "schema": SCHEMA,
        "status": "REJECTED_FRAGILE_TRAIN_NEGATIVE_VALIDATION_NO_TEST_ACTIVITY",
        "source_report_digest": EXPECTED_REPORT_DIGEST,
        "source_sha": EXPECTED_SOURCE_SHA,
        "historical_archive_sha256": EXPECTED_ARCHIVE_SHA,
        "factory_fingerprint": EXPECTED_CONTRACT_FINGERPRINT,
        "isolation_warning": "10k USDT per symbol/per profile historical cells, NOT one 500-USDT portfolio or realized orders",
        "training_conservative_positive_but_stress_negative": training_cost_fragile,
        "validation_both_symbols_both_profiles_negative": validation_negative,
        "historically_inspected_test_has_zero_trades": inspected_test_inactive,
        "trades_in_held_out_test_sufficient_to_validate": False,
        "past_source_has_been_inspected": True,
        "source_authenticity_independently_verified_here": False,
        "trade_engine_independently_replayed_here": False,
        "candidate_profitable_claim": False,
        "new_algorithm_created": False,
        "qualifies_for_paper_demo": False,
        "automatic_strategy_promotion": False,
        "research_only": True,
        "live_trading_authority": False,
        "per_symbol": per_symbol,
        "aggregated_cell_diagnostics_not_one_account": totals,
        "next_action": "reject_first_butterfly_v8_cost_fragile_implementation; require separately_preregistered_prospective_economic_edge",
    }
    return {**unsigned, "audit_sha256": _digest(unsigned)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.report.resolve() == args.output.resolve():
        raise ButterflyCostAuditError("audit cannot overwrite original report")
    result = audit(_read(args.report))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as fd:
        fd.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
        fd.flush()
        os.fsync(fd.fileno())
    os.replace(temporary, args.output)
    print(json.dumps({
        "status": result["status"],
        "audit_sha256": result["audit_sha256"],
        "qualifies_for_paper_demo": False,
        "live_trading_authority": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
