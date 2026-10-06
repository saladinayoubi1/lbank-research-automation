"""Bridge independently QA-attested composite Research evidence into VAL-40.

This module does not qualify, register, activate, or execute a strategy.  It
turns one exact RES-32 composite Research result into deterministic candidate
evidence for *fresh* runtime requalification only when:
- the Research producer is DONE and independently QA-attested,
- the exact producer receipt/report/config bind together,
- selection was training-only with no minimum-trade-count gate,
- validation exercised the mechanism and every conservative/stress BTC/ETH
  validation cell remained strictly positive.

Historical evidence is explicitly non-pristine and can never promote itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from typing import Any

from nexus_demo_archive_replay import ARCHIVE_SHA256
from nexus_research_missions import attested_predecessor

SCHEMA = "nexus.composite-validation-candidate.v1"
VERIFY_SCHEMA = "nexus.composite-validation-candidate-verification.v1"
COMPOSITE_RESEARCH_SCHEMA = "nexus.automatic-composite-research.v1"
PRODUCER_SCHEMA = "nexus.agent-composite-execution.v1"
TIMEFRAME = "minute15_with_completed_1h_4h"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
PROFILES = ("conservative", "stress")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeValidationCandidateError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeValidationCandidateError("candidate evidence is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validate_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(receipt)
    claimed = value.pop("receipt_digest", None)
    if (
        claimed != digest(value)
        or receipt.get("schema") != PRODUCER_SCHEMA
        or not _HEX40.fullmatch(str(receipt.get("source_sha", "")))
        or receipt.get("archive_sha256") != ARCHIVE_SHA256
        or not _HEX64.fullmatch(str(receipt.get("prior_ledger_digest", "")))
        or not _HEX64.fullmatch(str(receipt.get("ledger_digest", "")))
        or not _HEX64.fullmatch(str(receipt.get("report_digest", "")))
        or not _HEX64.fullmatch(str(receipt.get("config_fingerprint", "")))
        or not isinstance(receipt.get("lease_id"), str)
        or not receipt.get("lease_id")
        or len(receipt.get("lease_id")) > 160
        or not isinstance(receipt.get("mechanism"), str)
        or not re.fullmatch(r"[a-z][a-z0-9_]{2,79}", receipt.get("mechanism", ""))
        or receipt.get("research_only") is not True
        or receipt.get("auto_demo_promotion") is not False
        or receipt.get("live_enabled") is not False
        or receipt.get("independent_qa_complete") is not False
    ):
        raise CompositeValidationCandidateError("producer receipt binding or authority is invalid")
    return dict(receipt)


def _validate_report(report: Mapping[str, Any], receipt: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = dict(report)
    claimed = raw.pop("report_digest", None)
    selected = report.get("selected")
    screening = report.get("frontier_screening")
    rows = report.get("rows")
    if (
        claimed != digest(raw)
        or claimed != receipt.get("report_digest")
        or report.get("schema") != COMPOSITE_RESEARCH_SCHEMA
        or report.get("source_sha") != receipt.get("source_sha")
        or report.get("archive_sha256") != ARCHIVE_SHA256
        or report.get("status") != "EVALUATED_RESEARCH_ONLY"
        or report.get("selection_basis") != "frontier_training_only_tournament_then_full_replay"
        or report.get("historical_test_pristine") is not False
        or report.get("independent_future_data_required") is not True
        or report.get("research_only") is not True
        or report.get("auto_demo_promotion") is not False
        or report.get("live_enabled") is not False
        or report.get("qualification") != "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
        or report.get("ledger_digest") != receipt.get("ledger_digest")
        or not isinstance(selected, Mapping)
        or set(selected) != {
            "mechanism", "risk_variant", "entry_model",
            "factory_contract_digest", "fingerprint",
        }
        or selected.get("mechanism") != receipt.get("mechanism")
        or selected.get("fingerprint") != receipt.get("config_fingerprint")
        or selected.get("entry_model") != "closed_4h_1h_15m_next_open"
        or isinstance(selected.get("risk_variant"), bool)
        or not isinstance(selected.get("risk_variant"), int)
        or selected.get("risk_variant") not in {0, 1}
        or not _HEX64.fullmatch(str(selected.get("factory_contract_digest", "")))
        or not isinstance(screening, Mapping)
        or screening.get("schema") != "nexus.frontier-train-screen.v5"
        or screening.get("basis") != "training_partition_only_no_validation_or_historical_test_ranking"
        or screening.get("selected_mechanism") != selected.get("mechanism")
        or screening.get("no_minimum_trade_count_gate") is not True
        or screening.get("validation_used_for_selection") is not False
        or screening.get("historically_inspected_test_used_for_selection") is not False
        or not isinstance(rows, list)
    ):
        raise CompositeValidationCandidateError("research report selection/provenance is invalid")

    strategy_config = {
        "mechanism": selected["mechanism"],
        "risk_variant": selected["risk_variant"],
        "entry_model": selected["entry_model"],
        "factory_contract_digest": selected["factory_contract_digest"],
    }
    expected_fingerprint = digest({
        "config": strategy_config,
        "dataset": ARCHIVE_SHA256,
        "contract": COMPOSITE_RESEARCH_SCHEMA,
    })
    if expected_fingerprint != selected["fingerprint"]:
        raise CompositeValidationCandidateError("selected composite config fingerprint mismatch")

    validation = [dict(row) for row in rows if isinstance(row, Mapping) and row.get("part") == "validation"]
    expected_cells = {(symbol, profile) for symbol in SYMBOLS for profile in PROFILES}
    actual_cells = {
        (row.get("symbol"), row.get("profile"))
        for row in validation
    }
    if len(validation) != len(expected_cells) or actual_cells != expected_cells:
        raise CompositeValidationCandidateError("validation grid is missing or duplicated")
    for row in validation:
        if (
            row.get("mechanism") != selected["mechanism"]
            or row.get("config_fingerprint") != selected["fingerprint"]
            or row.get("timeframe") != TIMEFRAME
            or row.get("trade_count_limit") is not None
            or isinstance(row.get("closed_round_trips"), bool)
            or not isinstance(row.get("closed_round_trips"), int)
            or row.get("closed_round_trips") < 0
            or isinstance(row.get("net_return_pct"), bool)
            or not isinstance(row.get("net_return_pct"), (int, float))
            or not math.isfinite(float(row.get("net_return_pct")))
            or isinstance(row.get("max_drawdown_pct"), bool)
            or not isinstance(row.get("max_drawdown_pct"), (int, float))
            or not math.isfinite(float(row.get("max_drawdown_pct")))
            or row.get("halted_on_drawdown") is not False
        ):
            raise CompositeValidationCandidateError("validation row is incomplete or authority-invalid")
    validation.sort(key=lambda row: (str(row["symbol"]), str(row["profile"])))
    return strategy_config, validation


def build_candidate(
    manager_task: Mapping[str, Any],
    producer_receipt: Mapping[str, Any],
    research_report: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        attested = attested_predecessor(dict(manager_task))
    except Exception as exc:
        raise CompositeValidationCandidateError("Research task lacks exact independent QA") from exc

    receipt = _validate_receipt(producer_receipt)
    production = manager_task.get("result_evidence")
    qa = manager_task.get("verification_evidence")
    if (
        not isinstance(production, Mapping)
        or not isinstance(qa, Mapping)
        or manager_task.get("research_producer_lease_id") != receipt["lease_id"]
        or attested["research_predecessor_source_sha"] != receipt["source_sha"]
        or attested["research_predecessor_receipt_digest"] != receipt["receipt_digest"]
        or attested["research_predecessor_ledger_digest"] != receipt["ledger_digest"]
        or attested["research_predecessor_mechanism"] != receipt["mechanism"]
        or production.get("config_fingerprint") != receipt["config_fingerprint"]
        or production.get("prior_ledger_digest") != receipt["prior_ledger_digest"]
        or qa.get("qa_digest") != attested["research_predecessor_qa_digest"]
        or qa.get("qualification_authority") is not False
    ):
        raise CompositeValidationCandidateError("durable Agent Manager binding differs from producer proof")

    strategy_config, validation = _validate_report(research_report, receipt)
    total_trades = sum(int(row["closed_round_trips"]) for row in validation)
    all_positive = all(float(row["net_return_pct"]) > 0.0 for row in validation)
    if total_trades == 0:
        decision = "REJECTED_RESEARCH_VALIDATION"
        reasons = ["ZERO_ACTIVITY"]
        eligible = False
    elif not all_positive:
        decision = "REJECTED_RESEARCH_VALIDATION"
        reasons = ["NON_POSITIVE_VALIDATION_CELL"]
        eligible = False
    else:
        decision = "FORWARD_TO_VAL40"
        reasons = ["EXERCISED_AND_POSITIVE_ACROSS_VALIDATION_COST_PROFILES"]
        eligible = True

    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "proposal_kind": "composite_mechanism",
        "decision": decision,
        "reason_codes": reasons,
        "eligible_for_fresh_runtime_requalification": eligible,
        "research_task_id": manager_task.get("id"),
        "source_sha": receipt["source_sha"],
        "archive_sha256": receipt["archive_sha256"],
        "mechanism": receipt["mechanism"],
        "timeframe": TIMEFRAME,
        "strategy_config": strategy_config,
        "config_fingerprint": receipt["config_fingerprint"],
        "producer_lease_id": receipt["lease_id"],
        "producer_receipt_digest": receipt["receipt_digest"],
        "research_report_digest": receipt["report_digest"],
        "qa_digest": attested["research_predecessor_qa_digest"],
        "ledger_digest": receipt["ledger_digest"],
        "prior_ledger_digest": receipt["prior_ledger_digest"],
        "validation_rows": validation,
        "validation_digest": digest(validation),
        "total_validation_round_trips": total_trades,
        "no_minimum_trade_count_gate": True,
        "selection_used_validation_for_ranking": False,
        "selection_used_historical_test_for_ranking": False,
        "historical_test_pristine": False,
        "requires_fresh_runtime_data": True,
        "research_only": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "candidate_digest": digest(core)}


def verify_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "identity": False,
        "validation": False,
        "decision": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("candidate_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
            and core.get("proposal_kind") == "composite_mechanism"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)
        config = core.get("strategy_config")
        checks["identity"] = bool(
            isinstance(core.get("research_task_id"), str)
            and core["research_task_id"].startswith("P7-RESEARCH-COMPOSITE-")
            and _HEX40.fullmatch(str(core.get("source_sha", "")))
            and core.get("archive_sha256") == ARCHIVE_SHA256
            and isinstance(core.get("mechanism"), str)
            and isinstance(config, Mapping)
            and config.get("mechanism") == core.get("mechanism")
            and _HEX64.fullmatch(str(config.get("factory_contract_digest", "")))
            and core.get("config_fingerprint") == digest({
                "config": dict(config),
                "dataset": ARCHIVE_SHA256,
                "contract": COMPOSITE_RESEARCH_SCHEMA,
            })
            and all(_HEX64.fullmatch(str(core.get(key, ""))) for key in (
                "producer_receipt_digest", "research_report_digest", "qa_digest",
                "ledger_digest", "prior_ledger_digest", "validation_digest",
            ))
        )
        rows = core.get("validation_rows")
        cells = {
            (row.get("symbol"), row.get("profile"))
            for row in rows if isinstance(row, Mapping)
        } if isinstance(rows, list) else set()
        checks["validation"] = bool(
            isinstance(rows, list)
            and len(rows) == 4
            and cells == {(symbol, profile) for symbol in SYMBOLS for profile in PROFILES}
            and core.get("validation_digest") == digest(rows)
            and core.get("total_validation_round_trips")
                == sum(int(row.get("closed_round_trips", -1)) for row in rows)
            and core.get("no_minimum_trade_count_gate") is True
            and core.get("selection_used_validation_for_ranking") is False
            and core.get("selection_used_historical_test_for_ranking") is False
            and core.get("historical_test_pristine") is False
            and core.get("requires_fresh_runtime_data") is True
        )
        eligible = core.get("eligible_for_fresh_runtime_requalification")
        checks["decision"] = bool(
            (
                core.get("decision") == "FORWARD_TO_VAL40"
                and eligible is True
                and core.get("reason_codes")
                    == ["EXERCISED_AND_POSITIVE_ACROSS_VALIDATION_COST_PROFILES"]
                and core.get("total_validation_round_trips", 0) > 0
                and all(float(row["net_return_pct"]) > 0.0 for row in rows)
            )
            or (
                core.get("decision") == "REJECTED_RESEARCH_VALIDATION"
                and eligible is False
                and core.get("reason_codes") in (
                    ["ZERO_ACTIVITY"], ["NON_POSITIVE_VALIDATION_CELL"]
                )
            )
        )
        checks["authority"] = bool(
            core.get("research_only") is True
            and core.get("paper_only") is True
            and core.get("candidate_state_created") is False
            and core.get("qualification_authority") is False
            and core.get("registry_mutation_authority") is False
            and core.get("promotion_authority") is False
            and core.get("paper_execution_authority") is False
            and core.get("automatic_strategy_promotion") is False
            and core.get("live_trading_authority") is False
        )
    except Exception:
        pass
    decision = "pass" if all(checks.values()) else "reject"
    result = {
        "schema_version": VERIFY_SCHEMA,
        "decision": decision,
        "checks": checks,
        "candidate_digest": value.get("candidate_digest"),
    }
    return {**result, "verification_digest": digest(result)}
