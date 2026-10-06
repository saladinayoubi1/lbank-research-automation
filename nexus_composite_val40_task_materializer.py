"""Materialize verified composite VAL-40 candidates into Agent Manager tasks.

Rejected historical candidates remain durable evidence only.  Only a candidate
whose standalone verifier passes and whose decision is FORWARD_TO_VAL40 becomes
a fresh runtime validation task.  Materialization grants no qualification,
registry, Runtime/Paper, or Live authority.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from nexus_composite_validation_candidate import verify_candidate


class CompositeVal40MaterializerError(ValueError):
    pass


def _task(candidate: Mapping[str, Any], verification: Mapping[str, Any]) -> dict[str, Any]:
    digest = str(candidate.get("candidate_digest", ""))
    return {
        "id": "COMPOSITE-VAL40-" + digest,
        "title": "Fresh canonical runtime requalification of QA-attested composite candidate",
        "phase": 7,
        "gate": 17,
        "status": "READY",
        "priority": 74,
        "dependencies": [],
        "required_capabilities": ["data_validation"],
        "required_resources": ["github-cloud"],
        "preferred_resources": ["github-cloud"],
        "authority": 2,
        "acceptance": [
            "producer is research-agent and uses canonical public Bybit closed candles only",
            "exact composite candidate/config/factory contract remains unchanged",
            "1000-candle 15m/1h/4h BTC/ETH datasets are bound with exact window anchors",
            "conservative and stress profiles are replayed deterministically with no minimum trade-count gate",
            "independent verifier is qa-verifier-agent and replays the exact producer source/window",
            "no qualification, registry mutation, Runtime/Paper activation, automatic promotion or Live authority",
        ],
        "composite_val40_task": True,
        "required_producer": "research-agent",
        "required_verifier": "qa-verifier-agent",
        "composite_val40_candidate": deepcopy(dict(candidate)),
        "composite_val40_candidate_verification": deepcopy(dict(verification)),
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def materialize_candidate_tasks(
    definition: Mapping[str, Any],
    candidate: Mapping[str, Any],
    verification: Mapping[str, Any],
) -> dict[str, Any]:
    result = deepcopy(dict(definition))
    tasks = result.get("tasks")
    if not isinstance(tasks, list):
        raise CompositeVal40MaterializerError("Agent Manager definition tasks are unavailable")
    computed = verify_candidate(candidate)
    if computed.get("decision") != "pass" or dict(verification) != computed:
        raise CompositeVal40MaterializerError("composite VAL-40 candidate verification rejected")

    forward = candidate.get("decision") == "FORWARD_TO_VAL40"
    eligible = candidate.get("eligible_for_fresh_runtime_requalification") is True
    if not forward or not eligible:
        if forward != eligible:
            raise CompositeVal40MaterializerError("candidate decision/eligibility is inconsistent")
        return result

    task = _task(candidate, verification)
    existing = [row for row in tasks if isinstance(row, Mapping) and row.get("id") == task["id"]]
    if existing:
        if len(existing) != 1 or dict(existing[0]) != task:
            raise CompositeVal40MaterializerError("composite VAL-40 task definition collision")
        return result
    tasks.append(task)
    return result
