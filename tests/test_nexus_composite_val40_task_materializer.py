from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nexus_composite_val40_task_materializer import (
    CompositeVal40TaskMaterializerError,
    materialize_composite_val40_candidates,
    task_id,
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _candidate(*, eligible=True):
    decision = "FORWARD_TO_VAL40" if eligible else "REJECTED_RESEARCH_VALIDATION"
    core = {
        "schema_version": "nexus.composite-validation-candidate.v2",
        "system_map_node": "VAL-40",
        "research_task_id": "P7-RESEARCH-COMPOSITE-015",
        "producer_lease_id": "lease-015",
        "source_sha": "a" * 40,
        "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "timeframe": "minute15",
        "strategy_config": {
            "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
            "risk_variant": 0,
            "entry_model": "next_open",
            "factory_contract_digest": "b" * 64,
        },
        "config_fingerprint": "c" * 64,
        "research_report_digest": "d" * 64,
        "producer_receipt_digest": "e" * 64,
        "qa_digest": "f" * 64,
        "decision": decision,
        "reason_codes": (
            ["RESEARCH_VALIDATION_POSITIVE_AND_EXERCISED"]
            if eligible else ["ZERO_ACTIVITY"]
        ),
        "eligible_for_fresh_runtime_requalification": eligible,
        "requires_fresh_runtime_data": eligible,
        "no_minimum_trade_count_gate": True,
        "research_only": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "research_task": {},
        "producer_receipt": {},
        "research_report": {},
    }
    # Tests use a patched verifier below; candidate digest remains deterministic.
    return {**core, "candidate_digest": _digest(core)}


def _verification(candidate):
    core = {
        "schema_version": "nexus.composite-validation-candidate-verification.v2",
        "decision": "pass",
        "checks": {
            "schema": True,
            "digest": True,
            "task": True,
            "producer": True,
            "qa": True,
            "report": True,
            "decision": True,
            "authority": True,
        },
        "candidate_digest": candidate["candidate_digest"],
    }
    return {**core, "verification_digest": _digest(core)}


def _contract(candidate):
    core = {
        "schema_version": "nexus.composite-val40-execution-contract.v1",
        "system_map_node": "VAL-40",
        "candidate_digest": candidate["candidate_digest"],
        "candidate_verification_digest": "1" * 64,
        "research_task_id": candidate["research_task_id"],
        "candidate_source_sha": candidate["source_sha"],
        "mechanism": candidate["mechanism"],
        "timeframe": candidate["timeframe"],
        "strategy_config": dict(candidate["strategy_config"]),
        "config_fingerprint": candidate["config_fingerprint"],
        "requires_fresh_runtime_data": True,
        "no_minimum_trade_count_gate": True,
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
    return {**core, "execution_contract_digest": _digest(core)}


def test_materializer_adds_only_forward_candidate_and_keeps_dispatch_disabled(monkeypatch):
    import nexus_composite_val40_task_materializer as materializer

    forwarded = _candidate(eligible=True)
    rejected = _candidate(eligible=False)
    vf = _verification(forwarded)
    vr = _verification(rejected)
    contract = _contract(forwarded)

    monkeypatch.setattr(materializer, "verify_candidate", lambda row: vf if row is forwarded else vr)
    monkeypatch.setattr(materializer, "build_execution_contract", lambda c, v: deepcopy(contract))
    monkeypatch.setattr(
        materializer,
        "verify_execution_contract",
        lambda c: {"decision": "pass", "verification_digest": "2" * 64},
    )

    definition = {"schema_version": 1, "tasks": []}
    result = materialize_composite_val40_candidates(
        definition, [(rejected, vr), (forwarded, vf)]
    )
    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert task["id"] == task_id(forwarded["candidate_digest"])
    assert task["status"] == "BLOCKED"
    assert task["composite_val40_task"] is True
    assert task["composite_val40_dispatch_enabled"] is False
    assert task["required_producer"] == "research-agent"
    assert task["required_verifier"] == "qa-verifier-agent"
    assert task["authority"] == 2
    assert task["composite_val40_execution_contract"] == contract


def test_materializer_is_idempotent_and_collision_fails_closed(monkeypatch):
    import nexus_composite_val40_task_materializer as materializer

    candidate = _candidate()
    verification = _verification(candidate)
    contract = _contract(candidate)
    monkeypatch.setattr(materializer, "verify_candidate", lambda row: verification)
    monkeypatch.setattr(materializer, "build_execution_contract", lambda c, v: deepcopy(contract))
    monkeypatch.setattr(
        materializer,
        "verify_execution_contract",
        lambda c: {"decision": "pass", "verification_digest": "2" * 64},
    )

    definition = {"schema_version": 1, "tasks": []}
    first = materialize_composite_val40_candidates(definition, [(candidate, verification)])
    second = materialize_composite_val40_candidates(first, [(candidate, verification)])
    assert first == second

    collided = deepcopy(first)
    collided["tasks"][0]["required_verifier"] = "wrong"
    with pytest.raises(CompositeVal40TaskMaterializerError, match="collides"):
        materialize_composite_val40_candidates(collided, [(candidate, verification)])


def test_invalid_verification_never_materializes(monkeypatch):
    import nexus_composite_val40_task_materializer as materializer

    candidate = _candidate()
    verification = _verification(candidate)
    monkeypatch.setattr(
        materializer,
        "verify_candidate",
        lambda row: {**verification, "decision": "reject"},
    )
    with pytest.raises(CompositeVal40TaskMaterializerError, match="verification"):
        materialize_composite_val40_candidates(
            {"schema_version": 1, "tasks": []},
            [(candidate, verification)],
        )
