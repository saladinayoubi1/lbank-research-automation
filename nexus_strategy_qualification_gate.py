"""Deterministic QUAL-42 gate for independently verified Strategy Finder work.

A valid QA-41 receipt may authorize only admission into the reviewed REG-50
strategy/config registry.  This module never writes the registry, never adds a
strategy to the Demo matrix, never executes Paper, and never grants Live
authority.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from nexus_strategy_independent_qa import (
    StrategyIndependentQaError,
    validate_task,
    verify_receipt,
)
from strategy_registry import (
    APPROVED_STRATEGY_SCHEMA,
    build_approved_strategy_record,
    validate_approved_strategy_record,
)

SCHEMA = "nexus.strategy-qualification-gate.v1"
POLICY_VERSION = "nexus.qual-42.independent-qa.v1"


class StrategyQualificationError(ValueError):
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
        raise StrategyQualificationError(
            "qualification artifact is not canonical JSON"
        ) from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _validated_task(task: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(task, Mapping):
        raise StrategyQualificationError("QUAL-42 task must be a mapping")
    source_sha = str(task.get("source_sha", ""))
    try:
        return validate_task(task, source_sha)
    except StrategyIndependentQaError as exc:
        raise StrategyQualificationError("QUAL-42 received an invalid QA-41 task") from exc


def qualify_for_registry(
    task: Mapping[str, Any],
    qa_receipt: Mapping[str, Any],
    *,
    expected_qa_lease_id: str,
) -> dict[str, Any]:
    row = _validated_task(task)
    if (
        not isinstance(expected_qa_lease_id, str)
        or not expected_qa_lease_id
        or len(expected_qa_lease_id) > 160
    ):
        raise StrategyQualificationError("QUAL-42 expected QA lease identity is invalid")

    receipt_valid = bool(
        isinstance(qa_receipt, Mapping)
        and verify_receipt(
            qa_receipt,
            row,
            lease_id=expected_qa_lease_id,
            execution_source_sha=row["source_sha"],
        )
    )
    raw_receipt_digest = (
        qa_receipt.get("qa_receipt_digest")
        if isinstance(qa_receipt, Mapping)
        else None
    )
    observed_receipt_digest = (
        str(raw_receipt_digest)
        if isinstance(raw_receipt_digest, str)
        and len(raw_receipt_digest) == 64
        and all(ch in "0123456789abcdef" for ch in raw_receipt_digest)
        else None
    )

    reason_codes = (
        ["INDEPENDENT_QA_VERIFIED", "EXACT_SOURCE_CONFIG_DATASET_BOUND"]
        if receipt_valid
        else ["INDEPENDENT_QA_RECEIPT_REJECTED"]
    )
    core = {
        "schema_version": SCHEMA,
        "system_map_node": "QUAL-42",
        "qualification_policy_version": POLICY_VERSION,
        "registry_contract_version": APPROVED_STRATEGY_SCHEMA,
        "source_sha": row["source_sha"],
        "proposal_digest": row["proposal_digest"],
        "qa_task_digest": row["task_digest"],
        "expected_qa_lease_id": expected_qa_lease_id,
        "observed_qa_receipt_digest": observed_receipt_digest,
        "qualified": receipt_valid,
        "reason_codes": reason_codes,
        "registry_admission_allowed": receipt_valid,
        "demo_matrix_membership": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_demo_admission": False,
        "paper_only": True,
        "live_trading_authority": False,
    }
    qualification_digest = _digest(core)
    approved_record = None
    if receipt_valid:
        approved_record = build_approved_strategy_record(
            source_sha=row["source_sha"],
            proposal_digest=row["proposal_digest"],
            qa_task_digest=row["task_digest"],
            qa_receipt_digest=str(qa_receipt["qa_receipt_digest"]),
            qualification_digest=qualification_digest,
            qualification_policy_version=POLICY_VERSION,
            family=row["family"],
            timeframe=row["timeframe"],
            variant_id=row["variant_id"],
            strategy_config=row["strategy_config"],
            strategy_config_digest=row["strategy_config_digest"],
            runtime_evidence=row["runtime_evidence"],
        )
        validate_approved_strategy_record(approved_record)

    return {
        **core,
        "qualification_digest": qualification_digest,
        "approved_strategy_record": approved_record,
    }


def verify_qualification(
    value: Mapping[str, Any],
    task: Mapping[str, Any],
    qa_receipt: Mapping[str, Any],
    *,
    expected_qa_lease_id: str,
) -> dict[str, Any]:
    try:
        expected = qualify_for_registry(
            task,
            qa_receipt,
            expected_qa_lease_id=expected_qa_lease_id,
        )
        passed = isinstance(value, Mapping) and dict(value) == expected
    except (StrategyQualificationError, StrategyIndependentQaError, ValueError):
        passed = False
    proof_core = {
        "schema_version": "nexus.strategy-qualification-verification.v1",
        "system_map_node": "QUAL-42",
        "decision": "pass" if passed else "reject",
        "qualification_digest": value.get("qualification_digest")
        if isinstance(value, Mapping)
        else None,
        "paper_only": True,
        "live_trading_authority": False,
    }
    return {**proof_core, "verification_digest": _digest(proof_core)}
