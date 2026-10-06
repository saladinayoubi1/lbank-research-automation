"""QUAL-42 gate for independently QA-verified composite VAL-40 candidates.

This is a typed extension of the existing NEXUS qualification layer.  It consumes
the persisted Agent Manager COMPOSITE-QA task and its accepted independent QA
receipt.  It never discovers/ranks strategies, mutates REG-50, activates
Runtime/Paper, or grants Live authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from nexus_composite_runtime_independent_qa import validate_task, verify_receipt

SCHEMA = "nexus.composite-strategy-qualification-gate.v1"
VERIFY_SCHEMA = "nexus.composite-strategy-qualification-gate-verification.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_WAITING = {"PENDING", "READY", "LEASED", "RUNNING", "VERIFYING"}
_REJECTED = {"BLOCKED", "QUARANTINED"}


class CompositeStrategyQualificationError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeStrategyQualificationError(
            "composite qualification value is not canonical JSON"
        ) from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_identity(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 200:
        raise CompositeStrategyQualificationError(f"{field} is invalid")
    return value


def evaluate_composite_qualification(manager_task: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(manager_task, Mapping):
        raise CompositeStrategyQualificationError(
            "Agent Manager composite QA task must be a mapping"
        )
    handoff = manager_task.get("qa_handoff_task")
    if not isinstance(handoff, Mapping):
        raise CompositeStrategyQualificationError("composite QA handoff is unavailable")
    source_sha = str(handoff.get("source_sha", ""))
    try:
        verified_task = validate_task(handoff, source_sha)
    except Exception as exc:
        raise CompositeStrategyQualificationError(
            "composite QA handoff verification failed"
        ) from exc

    task_id = _bounded_identity(manager_task.get("id"), "task id")
    status = _bounded_identity(manager_task.get("status"), "task status")
    authority = manager_task.get("authority")
    producer = verified_task.get("producer")
    if not isinstance(producer, Mapping):
        raise CompositeStrategyQualificationError("physical VAL-40 producer proof is missing")

    if (
        task_id != verified_task.get("id")
        or manager_task.get("qa_verifier_only") is not True
        or manager_task.get("qa_dispatch_enabled") is not True
        or manager_task.get("required_verifier") != "qa-verifier-agent"
        or isinstance(authority, bool)
        or not isinstance(authority, int)
        or authority < 0
        or authority > 2
        or manager_task.get("producer") not in (None, "")
    ):
        raise CompositeStrategyQualificationError(
            "Agent Manager composite QA authority boundary is invalid"
        )

    config = producer.get("strategy_config")
    evaluations = producer.get("evaluations")
    if (
        not isinstance(config, Mapping)
        or not config
        or not isinstance(evaluations, list)
        or not evaluations
        or producer.get("evaluations_digest") != digest(evaluations)
        or not isinstance(producer.get("mechanism"), str)
        or not producer.get("mechanism")
        or not isinstance(producer.get("timeframe"), str)
        or not producer.get("timeframe")
        or not _HEX64.fullmatch(str(producer.get("config_fingerprint", "")))
    ):
        raise CompositeStrategyQualificationError(
            "physical VAL-40 strategy identity or runtime evidence is invalid"
        )

    common = {
        "schema_version": SCHEMA,
        "system_map_node": "QUAL-42",
        "qualification_kind": "composite_runtime_independent_qa",
        "composite_qa_task_id": task_id,
        "qa_task_digest": verified_task["task_digest"],
        "source_sha": verified_task["source_sha"],
        "producer_workflow_run_id": verified_task["producer_workflow_run_id"],
        "candidate_digest": verified_task["candidate_digest"],
        "requalification_digest": verified_task["requalification_digest"],
        "requalification_verification_digest":
            verified_task["requalification_verification_digest"],
        "evaluations_digest": verified_task["evaluations_digest"],
        "runtime_as_of_ms": verified_task["runtime_as_of_ms"],
        "mechanism": producer["mechanism"],
        "timeframe": producer["timeframe"],
        "strategy_config": dict(config),
        "strategy_config_digest": digest(dict(config)),
        "config_fingerprint": producer["config_fingerprint"],
        "runtime_evidence": [dict(row) for row in evaluations],
        "runtime_evidence_digest": producer["evaluations_digest"],
        "qa_handoff_task": dict(verified_task),
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
            raise CompositeStrategyQualificationError(
                "DONE composite QA task lacks the exact accepted verifier receipt"
            )
        core = {
            **common,
            "decision": "QUALIFIED_FOR_REGISTRY",
            "qualified": True,
            "reason_codes": ["INDEPENDENT_COMPOSITE_QA_VERIFIED"],
            "registry_admission_allowed": True,
            "qa_lease_id": lease_id,
            "qa_receipt_digest": receipt["qa_receipt_digest"],
            "qa_receipt": dict(receipt),
        }
    elif status in _REJECTED:
        core = {
            **common,
            "decision": "REJECTED",
            "qualified": False,
            "reason_codes": [
                "INDEPENDENT_COMPOSITE_QA_BLOCKED"
                if status == "BLOCKED"
                else "INDEPENDENT_COMPOSITE_QA_QUARANTINED"
            ],
            "registry_admission_allowed": False,
            "qa_lease_id": None,
            "qa_receipt_digest": None,
            "qa_receipt": None,
        }
    elif status in _WAITING:
        core = {
            **common,
            "decision": "WAITING_FOR_QA",
            "qualified": False,
            "reason_codes": ["INDEPENDENT_COMPOSITE_QA_INCOMPLETE"],
            "registry_admission_allowed": False,
            "qa_lease_id": None,
            "qa_receipt_digest": None,
            "qa_receipt": None,
        }
    else:
        raise CompositeStrategyQualificationError(
            "Agent Manager composite QA task status is unsupported"
        )

    return {**core, "qualification_digest": digest(core)}


def verify_composite_qualification(value: Mapping[str, Any]) -> dict[str, Any]:
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
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "QUAL-42"
            and core.get("qualification_kind")
                == "composite_runtime_independent_qa"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)

        source_sha = str(core.get("source_sha", ""))
        embedded_task = core.get("qa_handoff_task")
        verified_task = (
            validate_task(embedded_task, source_sha)
            if isinstance(embedded_task, Mapping)
            else None
        )
        producer = (
            verified_task.get("producer")
            if isinstance(verified_task, Mapping)
            else None
        )
        runtime_evidence = core.get("runtime_evidence")
        strategy_config = core.get("strategy_config")
        checks["identity"] = bool(
            isinstance(verified_task, Mapping)
            and isinstance(producer, Mapping)
            and core.get("composite_qa_task_id") == verified_task.get("id")
            and core.get("qa_task_digest") == verified_task.get("task_digest")
            and _SHA40.fullmatch(source_sha)
            and source_sha == verified_task.get("source_sha")
            and core.get("producer_workflow_run_id")
                == verified_task.get("producer_workflow_run_id")
            and core.get("candidate_digest") == verified_task.get("candidate_digest")
            and core.get("requalification_digest")
                == verified_task.get("requalification_digest")
            and core.get("requalification_verification_digest")
                == verified_task.get("requalification_verification_digest")
            and core.get("evaluations_digest") == verified_task.get("evaluations_digest")
            and core.get("runtime_as_of_ms") == verified_task.get("runtime_as_of_ms")
            and core.get("mechanism") == producer.get("mechanism")
            and core.get("timeframe") == producer.get("timeframe")
            and isinstance(strategy_config, Mapping)
            and bool(strategy_config)
            and strategy_config == producer.get("strategy_config")
            and core.get("strategy_config_digest") == digest(dict(strategy_config))
            and core.get("config_fingerprint") == producer.get("config_fingerprint")
            and isinstance(runtime_evidence, list)
            and bool(runtime_evidence)
            and runtime_evidence == producer.get("evaluations")
            and core.get("runtime_evidence_digest") == digest(runtime_evidence)
            and core.get("runtime_evidence_digest") == producer.get("evaluations_digest")
        )

        decision = core.get("decision")
        qualified = core.get("qualified")
        admission = core.get("registry_admission_allowed")
        qa_lease = core.get("qa_lease_id")
        qa_receipt_digest = core.get("qa_receipt_digest")
        embedded_receipt = core.get("qa_receipt")
        receipt_valid = bool(
            isinstance(verified_task, Mapping)
            and isinstance(qa_lease, str)
            and bool(qa_lease)
            and len(qa_lease) <= 160
            and isinstance(embedded_receipt, Mapping)
            and embedded_receipt.get("qa_receipt_digest") == qa_receipt_digest
            and verify_receipt(
                embedded_receipt,
                verified_task,
                lease_id=qa_lease,
                execution_source_sha=source_sha,
            )
        )
        checks["decision"] = bool(
            (
                decision == "QUALIFIED_FOR_REGISTRY"
                and qualified is True
                and admission is True
                and core.get("reason_codes")
                    == ["INDEPENDENT_COMPOSITE_QA_VERIFIED"]
                and _HEX64.fullmatch(str(qa_receipt_digest or ""))
                and receipt_valid
            )
            or (
                decision in {"REJECTED", "WAITING_FOR_QA"}
                and qualified is False
                and admission is False
                and isinstance(core.get("reason_codes"), list)
                and bool(core.get("reason_codes"))
                and qa_lease is None
                and qa_receipt_digest is None
                and embedded_receipt is None
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
    return {**result, "verification_digest": digest(result)}
