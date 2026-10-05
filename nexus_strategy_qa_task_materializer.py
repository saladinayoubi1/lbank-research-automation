"""Materialize verified QA-41 handoff tasks into the repository Agent Manager definition.

Fail closed: this module only accepts a cryptographically self-consistent QA
handoff whose verification artifact exactly matches verify_handoff(). It adds
deterministic verifier-only work definitions; it never dispatches, qualifies,
promotes, executes Paper, or grants Live authority.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nexus_strategy_review_qa_handoff import qa_task_id, verify_handoff


class StrategyQaTaskMaterializerError(ValueError):
    pass


def _validate_verification(handoff: Mapping[str, Any], verification: Mapping[str, Any]) -> None:
    computed = verify_handoff(handoff)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise StrategyQaTaskMaterializerError("QA handoff verification is missing, stale, or rejected")


def _definition_task(task: Mapping[str, Any]) -> dict[str, Any]:
    if (
        task.get("task_kind") != "strategy_review_independent_qa"
        or task.get("system_map_node") != "QA-41"
        or task.get("required_verifier") != "qa-verifier-agent"
        or task.get("paper_only") is not True
        or task.get("candidate_creation_authority") is not False
        or task.get("qualification_authority") is not False
        or task.get("promotion_authority") is not False
        or task.get("paper_execution_authority") is not False
        or task.get("automatic_strategy_promotion") is not False
        or task.get("live_trading_authority") is not False
    ):
        raise StrategyQaTaskMaterializerError("QA task authority boundary changed")
    task_id = str(task.get("id", ""))
    proposal_digest = str(task.get("proposal_digest", ""))
    expected_id = qa_task_id(
        proposal_digest,
        str(task.get("source_sha", "")),
        str(task.get("requalification_digest", "")),
    )
    if task_id != expected_id:
        raise StrategyQaTaskMaterializerError("QA task identity is not exact-epoch deterministic")
    return {
        "id": task_id,
        "title": f"Independent QA replay for strategy proposal {proposal_digest[:12]}",
        "phase": 7,
        "gate": 17,
        "status": "READY",
        "priority": 92,
        "dependencies": [],
        "required_capabilities": ["data_validation"],
        "required_resources": ["github-cloud"],
        "preferred_resources": ["github-cloud"],
        "authority": 2,
        "acceptance": [
            "qa-verifier-agent independently replays exact strategy_config and source-bound datasets",
            "QA receipt binds source/proposal/result/requalification/config/dataset/lease identities",
            "no qualification, promotion, Paper execution, automatic Demo admission, or Live authority",
        ],
        "qa_verifier_only": True,
        "qa_dispatch_enabled": True,
        "required_verifier": "qa-verifier-agent",
        "qa_handoff_task": deepcopy(dict(task)),
    }


def materialize_qa_tasks(
    definition: Mapping[str, Any],
    handoff: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_verification(handoff, verification)
    if not isinstance(definition.get("tasks"), list):
        raise StrategyQaTaskMaterializerError("Agent Manager definition tasks are unavailable")
    if handoff.get("status") not in {"READY_FOR_QA", "NO_WORK"}:
        raise StrategyQaTaskMaterializerError("QA handoff status is invalid")

    result = deepcopy(dict(definition))
    existing = {row.get("id"): row for row in result["tasks"] if isinstance(row, Mapping)}
    additions = []
    for task in handoff.get("tasks", []):
        materialized = _definition_task(task)
        prior = existing.get(materialized["id"])
        if prior is not None:
            if prior != materialized:
                raise StrategyQaTaskMaterializerError("deterministic QA task collides with repository definition")
            continue
        additions.append(materialized)
        existing[materialized["id"]] = materialized
    result["tasks"].extend(additions)
    return result
