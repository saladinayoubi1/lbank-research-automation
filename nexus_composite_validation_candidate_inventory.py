"""Deterministic inventory for QA-attested composite VAL-40 candidates.

The inventory never ranks or selects a winner. Every supplied independently
QA-attested Research mission is evaluated by the existing self-contained
composite validation candidate gate. Forwarded and rejected rows are both
preserved so downstream fresh runtime requalification cannot silently omit a
failed mission or promote a hand-picked mechanism.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from nexus_composite_validation_candidate import build_candidate, verify_candidate
from nexus_research_missions import MISSION_SEQUENCE

SCHEMA = "nexus.composite-validation-candidate-inventory.v1"
VERIFY_SCHEMA = "nexus.composite-validation-candidate-inventory-verification.v1"


class CompositeCandidateInventoryError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CompositeCandidateInventoryError("inventory is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def build_inventory(entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Build one ordered, non-ranking inventory from exact Research proofs.

    Each entry must contain only: manager_task, producer_receipt, research_report.
    The mission order is repository-defined, not caller-defined. Duplicate or
    out-of-order tasks fail closed.
    """
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        raise CompositeCandidateInventoryError("candidate entries must be a sequence")

    rank = {task_id: index for index, task_id in enumerate(MISSION_SEQUENCE)}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    last_rank = -1

    for raw in entries:
        if not isinstance(raw, Mapping) or set(raw) != {
            "manager_task", "producer_receipt", "research_report"
        }:
            raise CompositeCandidateInventoryError("candidate inventory entry schema mismatch")
        manager = raw.get("manager_task")
        receipt = raw.get("producer_receipt")
        report = raw.get("research_report")
        if not all(isinstance(value, Mapping) for value in (manager, receipt, report)):
            raise CompositeCandidateInventoryError("candidate inventory proof is incomplete")
        task_id = manager.get("id")
        if task_id not in rank or task_id in seen:
            raise CompositeCandidateInventoryError("candidate mission identity is unknown or duplicated")
        if rank[task_id] <= last_rank:
            raise CompositeCandidateInventoryError("candidate missions must follow repository mission order")

        candidate = build_candidate(manager, receipt, report)
        verification = verify_candidate(candidate)
        if verification.get("decision") != "pass":
            raise CompositeCandidateInventoryError("self-contained composite candidate verification failed")
        decision = candidate.get("decision")
        if decision not in {"FORWARD_TO_VAL40", "REJECTED_RESEARCH_VALIDATION"}:
            raise CompositeCandidateInventoryError("unsupported composite candidate decision")

        rows.append({
            "research_task_id": task_id,
            "decision": decision,
            "candidate_digest": candidate["candidate_digest"],
            "candidate_verification_digest": verification["verification_digest"],
            "candidate": candidate,
            "candidate_verification": verification,
        })
        seen.add(task_id)
        last_rank = rank[task_id]

    forwarded = [
        row["research_task_id"] for row in rows
        if row["decision"] == "FORWARD_TO_VAL40"
    ]
    rejected = [
        row["research_task_id"] for row in rows
        if row["decision"] == "REJECTED_RESEARCH_VALIDATION"
    ]
    core = {
        "schema_version": SCHEMA,
        "system_map_node": "VAL-40",
        "selection_basis": "no_ranking_each_qa_attested_mission_evaluated_independently",
        "mission_order": [row["research_task_id"] for row in rows],
        "candidate_count": len(rows),
        "forwarded_task_ids": forwarded,
        "rejected_task_ids": rejected,
        "candidates": rows,
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
    return {**core, "inventory_digest": digest(core)}


def verify_inventory(value: Mapping[str, Any]) -> dict[str, Any]:
    checks = {
        "schema": False,
        "digest": False,
        "order": False,
        "proofs": False,
        "partition": False,
        "authority": False,
    }
    try:
        core = dict(value)
        claimed = core.pop("inventory_digest", None)
        checks["schema"] = bool(
            core.get("schema_version") == SCHEMA
            and core.get("system_map_node") == "VAL-40"
            and core.get("selection_basis")
            == "no_ranking_each_qa_attested_mission_evaluated_independently"
        )
        checks["digest"] = isinstance(claimed, str) and claimed == digest(core)

        rows = core.get("candidates")
        mission_order = core.get("mission_order")
        rank = {task_id: index for index, task_id in enumerate(MISSION_SEQUENCE)}
        checks["order"] = bool(
            isinstance(rows, list)
            and isinstance(mission_order, list)
            and len(rows) == core.get("candidate_count")
            and mission_order == [row.get("research_task_id") for row in rows]
            and len(mission_order) == len(set(mission_order))
            and all(task_id in rank for task_id in mission_order)
            and all(
                rank[mission_order[i]] < rank[mission_order[i + 1]]
                for i in range(max(0, len(mission_order) - 1))
            )
        )

        proof_ok = True
        decisions: dict[str, str] = {}
        if not isinstance(rows, list):
            proof_ok = False
        else:
            for row in rows:
                if not isinstance(row, Mapping):
                    proof_ok = False
                    break
                candidate = row.get("candidate")
                verification = row.get("candidate_verification")
                computed = verify_candidate(candidate) if isinstance(candidate, Mapping) else {}
                task_id = (
                    candidate.get("research_task_id")
                    if isinstance(candidate, Mapping)
                    else None
                )
                if (
                    not isinstance(candidate, Mapping)
                    or not isinstance(verification, Mapping)
                    or computed.get("decision") != "pass"
                    or dict(verification) != computed
                    or row.get("research_task_id") != task_id
                    or row.get("candidate_digest") != candidate.get("candidate_digest")
                    or row.get("candidate_verification_digest")
                    != verification.get("verification_digest")
                    or row.get("decision") != candidate.get("decision")
                    or row.get("decision")
                    not in {"FORWARD_TO_VAL40", "REJECTED_RESEARCH_VALIDATION"}
                ):
                    proof_ok = False
                    break
                decisions[str(task_id)] = str(row["decision"])
        checks["proofs"] = proof_ok

        forwarded = core.get("forwarded_task_ids")
        rejected = core.get("rejected_task_ids")
        checks["partition"] = bool(
            isinstance(forwarded, list)
            and isinstance(rejected, list)
            and not (set(forwarded) & set(rejected))
            and forwarded == [
                task_id for task_id in mission_order
                if decisions.get(task_id) == "FORWARD_TO_VAL40"
            ]
            and rejected == [
                task_id for task_id in mission_order
                if decisions.get(task_id) == "REJECTED_RESEARCH_VALIDATION"
            ]
            and len(forwarded) + len(rejected) == len(mission_order)
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
        "inventory_digest": value.get("inventory_digest"),
    }
    return {**result, "verification_digest": digest(result)}
