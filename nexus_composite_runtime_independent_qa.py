"""QA-41 independent replay contract for fresh composite VAL-40 evidence.

The producer is the physical fresh-Bybit VAL-40 workflow.  This module never
discovers/selects a strategy, mutates QUAL-42/REG-50, activates Runtime/Paper,
or grants Live authority.  It creates verifier-only work only for a producer
that already returned QUALIFIED_FOR_REVIEW, then independently reconstructs the
same source/config/runtime clock through the existing requalification engine.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from nexus_composite_evidence_adequacy import CompositeObservationError, assess
from nexus_composite_runtime_requalification import (
    CompositeRuntimeRequalificationError,
    build_requalification,
    verify_requalification,
)

TASK_SCHEMA = "nexus.composite-runtime-qa-task.v1"
RECEIPT_SCHEMA = "nexus.composite-runtime-qa-receipt.v1"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class CompositeRuntimeQaError(ValueError):
    pass


Replay = Callable[[Mapping[str, Any], Mapping[str, Any], str, int, Path], Mapping[str, Any]]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeRuntimeQaError("composite QA evidence is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def task_id(requalification_digest: str) -> str:
    if not _HEX64.fullmatch(str(requalification_digest)):
        raise CompositeRuntimeQaError("producer requalification digest is invalid")
    return f"COMPOSITE-QA-{requalification_digest}"


def build_task(
    producer: Mapping[str, Any],
    producer_verification: Mapping[str, Any],
    *,
    producer_workflow_run_id: int,
) -> dict[str, Any]:
    computed = verify_requalification(producer)
    if (
        computed.get("decision") != "pass"
        or dict(producer_verification) != computed
        or producer.get("decision") != "QUALIFIED_FOR_REVIEW"
        or producer.get("qualified_for_review") is not True
        or isinstance(producer_workflow_run_id, bool)
        or not isinstance(producer_workflow_run_id, int)
        or producer_workflow_run_id < 1
        or not _SHA40.fullmatch(str(producer.get("requalification_source_sha", "")))
        or not _HEX64.fullmatch(str(producer.get("candidate_digest", "")))
        or not _HEX64.fullmatch(str(producer.get("requalification_digest", "")))
        or not _HEX64.fullmatch(str(producer.get("evaluations_digest", "")))
        or type(producer.get("runtime_as_of_ms")) is not int
        or producer.get("runtime_as_of_ms") <= 0
        or producer.get("candidate_state_created") is not False
        or producer.get("qualification_authority") is not False
        or producer.get("registry_mutation_authority") is not False
        or producer.get("promotion_authority") is not False
        or producer.get("paper_execution_authority") is not False
        or producer.get("automatic_strategy_promotion") is not False
        or producer.get("paper_only") is not True
        or producer.get("live_trading_authority") is not False
        or producer.get("private_credentials_used") is not False
    ):
        raise CompositeRuntimeQaError(
            "physical composite producer is not eligible for independent QA"
        )
    # Historical producer v1 records remain verifiable. Issuing a *new* QA
    # task requires independently audited chronology and cash arithmetic.
    try:
        observation = assess(producer)
    except CompositeObservationError as exc:
        raise CompositeRuntimeQaError(
            "independent composite chronology/accounting audit failed"
        ) from exc
    if observation["decision"] != "READY_FOR_INDEPENDENT_QA_ONLY":
        raise CompositeRuntimeQaError(
            "insufficient observation coverage for independent QA: "
            + ",".join(observation["reason_codes"])
        )
    core = {
        "schema_version": TASK_SCHEMA,
        "id": task_id(str(producer["requalification_digest"])),
        "task_kind": "composite_runtime_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "required_verifier": "qa-verifier-agent",
        "producer_role": "physical-composite-val40-requalification",
        "producer_workflow_run_id": producer_workflow_run_id,
        "source_sha": producer["requalification_source_sha"],
        "candidate_digest": producer["candidate_digest"],
        "requalification_digest": producer["requalification_digest"],
        "requalification_verification_digest": computed["verification_digest"],
        "evaluations_digest": producer["evaluations_digest"],
        "runtime_as_of_ms": producer["runtime_as_of_ms"],
        "producer": dict(producer),
        "producer_verification": dict(producer_verification),
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "task_digest": digest(core)}


def validate_task(task: Mapping[str, Any], execution_source_sha: str) -> dict[str, Any]:
    if not isinstance(task, Mapping):
        raise CompositeRuntimeQaError("composite QA task must be a mapping")
    row = dict(task)
    claimed = row.pop("task_digest", None)
    producer = row.get("producer")
    producer_verification = row.get("producer_verification")
    if not isinstance(producer, Mapping) or not isinstance(producer_verification, Mapping):
        raise CompositeRuntimeQaError("composite QA producer proof is missing")
    computed = verify_requalification(producer)
    run_id = row.get("producer_workflow_run_id")
    if (
        claimed != digest(row)
        or task.get("schema_version") != TASK_SCHEMA
        or task.get("task_kind") != "composite_runtime_independent_qa"
        or task.get("system_map_node") != "QA-41"
        or task.get("status") != "READY_FOR_QA_DISPATCH"
        or task.get("required_verifier") != "qa-verifier-agent"
        or task.get("producer_role") != "physical-composite-val40-requalification"
        or computed.get("decision") != "pass"
        or dict(producer_verification) != computed
        or producer.get("decision") != "QUALIFIED_FOR_REVIEW"
        or producer.get("qualified_for_review") is not True
        or task.get("id") != task_id(str(producer.get("requalification_digest", "")))
        or task.get("source_sha") != producer.get("requalification_source_sha")
        or execution_source_sha != task.get("source_sha")
        or not _SHA40.fullmatch(str(execution_source_sha))
        or task.get("candidate_digest") != producer.get("candidate_digest")
        or task.get("requalification_digest") != producer.get("requalification_digest")
        or task.get("requalification_verification_digest") != computed.get("verification_digest")
        or task.get("evaluations_digest") != producer.get("evaluations_digest")
        or task.get("runtime_as_of_ms") != producer.get("runtime_as_of_ms")
        or isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id < 1
        or task.get("research_only") is not True
        or task.get("paper_only") is not True
        or task.get("qualification_authority") is not False
        or task.get("registry_mutation_authority") is not False
        or task.get("runtime_activation_authority") is not False
        or task.get("promotion_authority") is not False
        or task.get("paper_execution_authority") is not False
        or task.get("automatic_strategy_promotion") is not False
        or task.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeQaError("composite QA task identity or authority binding failed")
    return dict(task)


def _default_replay(
    candidate: Mapping[str, Any],
    candidate_verification: Mapping[str, Any],
    source_sha: str,
    now_ms: int,
    state_root: Path,
) -> Mapping[str, Any]:
    return build_requalification(
        candidate,
        candidate_verification,
        source_sha=source_sha,
        now_ms=now_ms,
        state_root=state_root,
    )


def run_independent_qa(
    task: Mapping[str, Any],
    *,
    lease_id: str,
    execution_source_sha: str,
    state_root: str | Path,
    replay: Replay = _default_replay,
) -> dict[str, Any]:
    row = validate_task(task, execution_source_sha)
    if not isinstance(lease_id, str) or not lease_id or len(lease_id) > 160:
        raise CompositeRuntimeQaError("composite QA lease identity is invalid")
    producer = row["producer"]
    try:
        replayed = dict(
            replay(
                producer["candidate"],
                producer["candidate_verification"],
                execution_source_sha,
                int(producer["runtime_as_of_ms"]),
                Path(state_root).resolve(),
            )
        )
    except (CompositeRuntimeRequalificationError, KeyError, OSError, TypeError, ValueError) as exc:
        raise CompositeRuntimeQaError("independent composite runtime replay failed") from exc
    if (
        verify_requalification(replayed).get("decision") != "pass"
        or _canonical(replayed) != _canonical(producer)
    ):
        raise CompositeRuntimeQaError(
            "independent composite runtime replay differs from physical producer"
        )
    core = {
        "schema_version": RECEIPT_SCHEMA,
        "qa_lease_id": lease_id,
        "task_digest": row["task_digest"],
        "producer_workflow_run_id": row["producer_workflow_run_id"],
        "source_sha": row["source_sha"],
        "candidate_digest": row["candidate_digest"],
        "producer_requalification_digest": row["requalification_digest"],
        "producer_requalification_verification_digest":
            row["requalification_verification_digest"],
        "evaluations_digest": row["evaluations_digest"],
        "runtime_as_of_ms": row["runtime_as_of_ms"],
        "independent_qa_complete": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "qa_receipt_digest": digest(core)}


def verify_receipt(
    receipt: Mapping[str, Any],
    task: Mapping[str, Any],
    *,
    lease_id: str,
    execution_source_sha: str,
) -> bool:
    try:
        row = validate_task(task, execution_source_sha)
        core = dict(receipt)
        claimed = core.pop("qa_receipt_digest", None)
        return bool(
            claimed == digest(core)
            and receipt.get("schema_version") == RECEIPT_SCHEMA
            and receipt.get("qa_lease_id") == lease_id
            and receipt.get("task_digest") == row["task_digest"]
            and receipt.get("producer_workflow_run_id") == row["producer_workflow_run_id"]
            and receipt.get("source_sha") == row["source_sha"]
            and receipt.get("candidate_digest") == row["candidate_digest"]
            and receipt.get("producer_requalification_digest") == row["requalification_digest"]
            and receipt.get("producer_requalification_verification_digest")
                == row["requalification_verification_digest"]
            and receipt.get("evaluations_digest") == row["evaluations_digest"]
            and receipt.get("runtime_as_of_ms") == row["runtime_as_of_ms"]
            and receipt.get("independent_qa_complete") is True
            and receipt.get("qualification_authority") is False
            and receipt.get("registry_mutation_authority") is False
            and receipt.get("runtime_activation_authority") is False
            and receipt.get("promotion_authority") is False
            and receipt.get("paper_execution_authority") is False
            and receipt.get("automatic_strategy_promotion") is False
            and receipt.get("live_trading_authority") is False
        )
    except Exception:
        return False
