"""Materialize verified composite runtime QA-41 tasks into Agent Manager.

The resulting task is intentionally BLOCKED and dispatch-disabled.  This stage
only makes the independently verifiable producer proof durable and restart-safe.
A separate reviewed change must enable the verifier transport.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from nexus_composite_runtime_independent_qa import validate_task


class CompositeRuntimeQaTaskMaterializerError(ValueError):
    pass


def _definition_task(task: Mapping[str, Any]) -> dict[str, Any]:
    source_sha = str(task.get("source_sha", ""))
    try:
        validated = validate_task(task, source_sha)
    except Exception as exc:
        raise CompositeRuntimeQaTaskMaterializerError("composite QA task verification failed") from exc
    if validated != dict(task):
        raise CompositeRuntimeQaTaskMaterializerError("composite QA task is not canonical")
    if (
        task.get("task_kind") != "composite_runtime_independent_qa"
        or task.get("system_map_node") != "QA-41"
        or task.get("required_verifier") != "qa-verifier-agent"
        or task.get("paper_only") is not True
        or task.get("qualification_authority") is not False
        or task.get("registry_mutation_authority") is not False
        or task.get("runtime_activation_authority") is not False
        or task.get("promotion_authority") is not False
        or task.get("paper_execution_authority") is not False
        or task.get("automatic_strategy_promotion") is not False
        or task.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeQaTaskMaterializerError("composite QA authority boundary changed")
    return {
        "id": task["id"],
        "title": f"Independent QA for composite VAL-40 {str(task['candidate_digest'])[:12]}",
        "phase": 7,
        "gate": 17,
        "status": "BLOCKED",
        "blocked_reason": "independent composite runtime QA transport not enabled",
        "priority": 93,
        "dependencies": [],
        "required_capabilities": ["data_validation"],
        "required_resources": ["github-cloud"],
        "preferred_resources": ["github-cloud"],
        "authority": 2,
        "acceptance": [
            "qa-verifier-agent independently replays the exact physical VAL-40 producer at its bound source/runtime clock",
            "QA receipt binds producer workflow/source/candidate/requalification/evaluations/lease identities",
            "no qualification, registry mutation, Runtime/Paper activation, automatic promotion, or Live authority",
        ],
        "qa_verifier_only": True,
        "qa_dispatch_enabled": False,
        "required_verifier": "qa-verifier-agent",
        "qa_handoff_task": deepcopy(dict(task)),
    }


def materialize_composite_qa_task(
    definition: Mapping[str, Any],
    task: Mapping[str, Any],
    transport: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(definition.get("tasks"), list):
        raise CompositeRuntimeQaTaskMaterializerError("Agent Manager definition tasks are unavailable")
    materialized = _definition_task(task)
    if (
        transport.get("schema_version") != "nexus.composite-runtime-qa-transport.v1"
        or transport.get("task_digest") != task.get("task_digest")
        or transport.get("source_sha") != task.get("source_sha")
        or transport.get("candidate_digest") != task.get("candidate_digest")
        or transport.get("requalification_digest") != task.get("requalification_digest")
        or transport.get("required_verifier") != "qa-verifier-agent"
        or transport.get("paper_only") is not True
        or transport.get("qualification_authority") is not False
        or transport.get("registry_mutation_authority") is not False
        or transport.get("runtime_activation_authority") is not False
        or transport.get("paper_execution_authority") is not False
        or transport.get("automatic_strategy_promotion") is not False
        or transport.get("live_trading_authority") is not False
    ):
        raise CompositeRuntimeQaTaskMaterializerError("composite QA transport verification failed")

    result = deepcopy(dict(definition))
    existing = {row.get("id"): row for row in result["tasks"] if isinstance(row, Mapping)}
    prior = existing.get(materialized["id"])
    if prior is not None:
        if prior != materialized:
            raise CompositeRuntimeQaTaskMaterializerError("deterministic composite QA task collides with repository definition")
        return result
    result["tasks"].append(materialized)
    return result
