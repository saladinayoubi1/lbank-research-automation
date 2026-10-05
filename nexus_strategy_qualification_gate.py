"""QUAL-42 deterministic gate for independently reviewed Strategy Finder output.

The gate consumes the persisted Agent Manager QA task state.  It never selects
or ranks a strategy, mutates REG-50, activates Runtime/Paper, or grants Live
authority.  A positive decision only permits a later registry admission step.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from nexus_strategy_independent_qa import validate_task, verify_receipt
from nexus_strategy_requalification_contract import (
    APPROVED_FAMILIES,
    APPROVED_SYMBOLS,
    APPROVED_TIMEFRAMES,
)
from nexus_strategy_review_qa_handoff import qa_task_id

SCHEMA = "nexus.strategy-qualification-gate.v1"
VERIFY_SCHEMA = "nexus.strategy-qualification-gate-verification.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WAITING = {"PENDING", "READY", "LEASED", "RUNNING", "VERIFYING"}
_REJECTED = {"BLOCKED", "QUARANTINED"}
_RUNTIME_EVIDENCE_KEYS = {
    "symbol", "dataset_binding_sha256", "pipeline_digest",
    "qualification_digest", "last_open_time_ms",
}


class StrategyQualificationError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise StrategyQualificationError("qualification value is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise StrategyQualificationError(f"{field} is invalid")
    return value




def _verified_runtime_evidence(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != len(APPROVED_SYMBOLS):
        return False
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, Mapping) or set(row) != _RUNTIME_EVIDENCE_KEYS:
            return False
        symbol = row.get("symbol")
        last_open = row.get("last_open_time_ms")
        if (
            symbol not in APPROVED_SYMBOLS
            or symbol in seen
            or not _HEX64.fullmatch(str(row.get("dataset_binding_sha256", "")))
            or not _HEX64.fullmatch(str(row.get("pipeline_digest", "")))
            or not _HEX64.fullmatch(str(row.get("qualification_digest", "")))
            or isinstance(last_open, bool)
            or not isinstance(last_open, int)
            or last_open <= 0
        ):
            return False
        seen.add(str(symbol))
    return seen == set(APPROVED_SYMBOLS)

def evaluate_qualification(manager_task: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one materialized QA task without mutating any downstream state."""
    if not isinstance(manager_task, Mapping):
        raise StrategyQualificationError("Agent Manager QA task must be a mapping")
    handoff = manager_task.get("qa_handoff_task")
    if not isinstance(handoff, Mapping):
        raise StrategyQualificationError("QA handoff task is unavailable")
    source_sha = str(handoff.get("source_sha", ""))
    try:
        verified_task = validate_task(handoff, source_sha)
    except Exception as exc:
        raise StrategyQualificationError("QA handoff task verification failed") from exc

    task_id = _bounded_identity(manager_task.get("id"), "task id")
    status = _bounded_identity(manager_task.get("status"), "task status")
    required_verifier = manager_task.get("required_verifier")
    authority = manager_task.get("authority")
    if (
        task_id != verified_task["id"]
        or manager_task.get("qa_verifier_only") is not True
        or manager_task.get("qa_dispatch_enabled") is not True
        or required_verifier != "qa-verifier-agent"
        or isinstance(authority, bool)
        or not isinstance(authority, int)
        or authority < 0
        or authority > 2
        or manager_task.get("producer") not in (None, "")
    ):
        raise StrategyQualificationError("Agent Manager QA authority boundary is invalid")

    common = {
        "schema_version": SCHEMA,
        "system_map_node": "QUAL-42",
        "strategy_qa_task_id": task_id,
        "qa_task_digest": verified_task["task_digest"],
        "source_sha": verified_task["source_sha"],
        "proposal_digest": verified_task["proposal_digest"],
        "proposal_result_digest": verified_task["proposal_result_digest"],
        "requalification_digest": verified_task["requalification_digest"],
        "requalification_verification_digest": verified_task["requalification_verification_digest"],
        "family": verified_task["family"],
        "timeframe": verified_task["timeframe"],
        "variant_id": verified_task["variant_id"],
        "strategy_config": dict(verified_task["strategy_config"]),
        "strategy_config_digest": verified_task["strategy_config_digest"],
        "runtime_evidence": [dict(row) for row in verified_task["runtime_evidence"]],
        "runtime_evidence_digest": _digest(verified_task["runtime_evidence"]),
        "paper_only": True,
        "registry_mutation_performed": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }

    if status == "DONE":
        verifier = manager_task.get("verifier")
        lease_id = manager_task.get("lease_id")
        receipt = manager_task.get("verification_evidence")
        if (
            verifier != "qa-verifier-agent"
            or manager_task.get("assigned_worker") not in (None, "qa-verifier-agent")
            or not isinstance(lease_id, str)
            or not lease_id
            or len(lease_id) > 160
            or not isinstance(receipt, Mapping)
            or not verify_receipt(
                receipt,
                verified_task,
                lease_id=lease_id,
                execution_source_sha=source_sha,
            )
        ):
            raise StrategyQualificationError("DONE QA task lacks the exact accepted verifier receipt")
        core = {
            **common,
            "decision": "QUALIFIED_FOR_REGISTRY",
            "qualified": True,
            "reason_codes": ["INDEPENDENT_QA_VERIFIED"],
            "registry_admission_allowed": True,
            "qa_lease_id": lease_id,
            "qa_receipt_digest": receipt["qa_receipt_digest"],
        }
    elif status in _REJECTED:
        core = {
            **common,
            "decision": "REJECTED",
            "qualified": False,
            "reason_codes": [
                "INDEPENDENT_QA_BLOCKED" if status == "BLOCKED"
                else "INDEPENDENT_QA_QUARANTINED"
            ],
            "registry_admission_allowed": False,
            "qa_lease_id": None,
            "qa_receipt_digest": None,
        }
    elif status in _WAITING:
        core = {
            **common,
            "decision": "WAITING_FOR_QA",
            "qualified": False,
            "reason_codes": ["INDEPENDENT_QA_INCOMPLETE"],
            "registry_admission_allowed": False,
            "qa_lease_id": None,
            "qa_receipt_digest": None,
        }
    else:
        raise StrategyQualificationError("Agent Manager QA task status is unsupported")

    return {**core, "qualification_digest": _digest(core)}


def verify_qualification(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "identity": False,
        "decision": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("qualification_digest", None)
        checks["schema"] = core.get("schema_version") == SCHEMA and core.get("system_map_node") == "QUAL-42"
        checks["digest"] = isinstance(claimed, str) and claimed == _digest(core)
        proposal_digest = str(core.get("proposal_digest", ""))
        source_sha = str(core.get("source_sha", ""))
        requalification_digest = str(core.get("requalification_digest", ""))
        runtime_evidence = core.get("runtime_evidence")
        checks["identity"] = bool(
            isinstance(core.get("strategy_qa_task_id"), str)
            and _HEX64.fullmatch(str(core.get("qa_task_digest", "")))
            and _SHA40.fullmatch(source_sha)
            and _HEX64.fullmatch(proposal_digest)
            and _HEX64.fullmatch(str(core.get("proposal_result_digest", "")))
            and _HEX64.fullmatch(requalification_digest)
            and _HEX64.fullmatch(str(core.get("requalification_verification_digest", "")))
            and core.get("strategy_qa_task_id")
                == qa_task_id(proposal_digest, source_sha, requalification_digest)
            and core.get("family") in APPROVED_FAMILIES
            and core.get("timeframe") in APPROVED_TIMEFRAMES
            and isinstance(core.get("variant_id"), str)
            and bool(core.get("variant_id"))
            and isinstance(core.get("strategy_config"), Mapping)
            and bool(core.get("strategy_config"))
            and core.get("strategy_config_digest") == _digest(core.get("strategy_config"))
            and _verified_runtime_evidence(runtime_evidence)
            and _HEX64.fullmatch(str(core.get("runtime_evidence_digest", "")))
            and core.get("runtime_evidence_digest") == _digest(runtime_evidence)
        )
        decision = core.get("decision")
        qualified = core.get("qualified")
        admission = core.get("registry_admission_allowed")
        qa_lease = core.get("qa_lease_id")
        qa_receipt = core.get("qa_receipt_digest")
        checks["decision"] = bool(
            (
                decision == "QUALIFIED_FOR_REGISTRY"
                and qualified is True
                and admission is True
                and isinstance(core.get("reason_codes"), list)
                and core.get("reason_codes") == ["INDEPENDENT_QA_VERIFIED"]
                and isinstance(qa_lease, str)
                and bool(qa_lease)
                and _HEX64.fullmatch(str(qa_receipt or ""))
            )
            or (
                decision in {"REJECTED", "WAITING_FOR_QA"}
                and qualified is False
                and admission is False
                and isinstance(core.get("reason_codes"), list)
                and bool(core.get("reason_codes"))
                and qa_lease is None
                and qa_receipt is None
            )
        )
        checks["authority"] = bool(
            core.get("paper_only") is True
            and core.get("registry_mutation_performed") is False
            and core.get("runtime_activation_authority") is False
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
        "qualification_digest": value.get("qualification_digest"),
    }
    return {**result, "verification_digest": _digest(result)}
