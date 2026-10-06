"""Materialize verified composite VAL-40 candidates into Agent Manager definition.

The durable candidate store is evidence, not a runtime database.  This module
rebuilds a deterministic task definition from every independently verifiable
FORWARD_TO_VAL40 candidate.  Rejected candidates never become tasks.  Dispatch
is deliberately disabled until the bounded Runtime Worker contract is connected
in a separate reviewed change.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from nexus_composite_validation_candidate import verify_candidate
from nexus_composite_val40_contract import (
    build_execution_contract,
    verify_execution_contract,
)


class CompositeVal40TaskMaterializerError(ValueError):
    pass


def task_id(candidate_digest: str) -> str:
    if not isinstance(candidate_digest, str) or len(candidate_digest) != 64:
        raise CompositeVal40TaskMaterializerError("candidate digest identity is invalid")
    try:
        int(candidate_digest, 16)
    except ValueError as exc:
        raise CompositeVal40TaskMaterializerError("candidate digest identity is invalid") from exc
    return f"COMPOSITE-VAL40-{candidate_digest}"


def _definition_task(
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any] | None:
    computed = verify_candidate(candidate)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise CompositeVal40TaskMaterializerError(
            "composite VAL-40 candidate verification is missing, stale, or rejected"
        )

    if candidate.get("decision") != "FORWARD_TO_VAL40":
        if candidate.get("eligible_for_fresh_runtime_requalification") is True:
            raise CompositeVal40TaskMaterializerError(
                "rejected candidate cannot claim fresh runtime eligibility"
            )
        return None

    if (
        candidate.get("eligible_for_fresh_runtime_requalification") is not True
        or candidate.get("requires_fresh_runtime_data") is not True
        or candidate.get("paper_only") is not True
        or candidate.get("candidate_state_created") is not False
        or candidate.get("qualification_authority") is not False
        or candidate.get("registry_mutation_authority") is not False
        or candidate.get("promotion_authority") is not False
        or candidate.get("paper_execution_authority") is not False
        or candidate.get("automatic_strategy_promotion") is not False
        or candidate.get("live_trading_authority") is not False
    ):
        raise CompositeVal40TaskMaterializerError(
            "composite VAL-40 candidate authority boundary changed"
        )

    contract = build_execution_contract(candidate, verification)
    contract_verification = verify_execution_contract(contract)
    if contract_verification.get("decision") != "pass":
        raise CompositeVal40TaskMaterializerError(
            "composite VAL-40 execution contract verification failed"
        )

    candidate_digest = str(candidate.get("candidate_digest", ""))
    return {
        "id": task_id(candidate_digest),
        "title": f"Fresh VAL-40 replay for composite candidate {candidate_digest[:12]}",
        "phase": 7,
        "gate": 17,
        "status": "BLOCKED",
        "blocked_reason": "fresh composite VAL-40 worker contract not enabled",
        "priority": 91,
        "dependencies": [],
        "required_capabilities": ["data_validation"],
        "required_resources": ["github-cloud"],
        "preferred_resources": ["github-cloud"],
        "authority": 2,
        "acceptance": [
            "research-agent replays the exact verified composite configuration on fresh canonical Bybit closed candles",
            "independent qa-verifier-agent reproduces the exact producer requalification before any QUAL-42 admission",
            "no candidate state, registry mutation, Runtime/Paper execution, automatic promotion, or Live authority",
        ],
        "composite_val40_task": True,
        "composite_val40_dispatch_enabled": False,
        "required_producer": "research-agent",
        "required_verifier": "qa-verifier-agent",
        "composite_val40_execution_contract": deepcopy(contract),
        "composite_val40_contract_verification": deepcopy(contract_verification),
    }


def materialize_composite_val40_candidates(
    definition: Mapping[str, Any],
    candidates: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, Any]:
    if not isinstance(definition.get("tasks"), list):
        raise CompositeVal40TaskMaterializerError(
            "Agent Manager definition tasks are unavailable"
        )

    result = deepcopy(dict(definition))
    existing = {
        row.get("id"): row
        for row in result["tasks"]
        if isinstance(row, Mapping) and row.get("id")
    }
    additions: list[dict[str, Any]] = []

    ordered = sorted(
        candidates,
        key=lambda pair: str(pair[0].get("candidate_digest", "")),
    )
    seen: set[str] = set()
    for candidate, verification in ordered:
        materialized = _definition_task(candidate, verification)
        if materialized is None:
            continue
        identity = materialized["id"]
        if identity in seen:
            raise CompositeVal40TaskMaterializerError(
                "duplicate composite VAL-40 candidate identity"
            )
        seen.add(identity)
        prior = existing.get(identity)
        if prior is not None:
            if prior != materialized:
                raise CompositeVal40TaskMaterializerError(
                    "deterministic composite VAL-40 task collides with repository definition"
                )
            continue
        additions.append(materialized)
        existing[identity] = materialized

    result["tasks"].extend(additions)
    return result
