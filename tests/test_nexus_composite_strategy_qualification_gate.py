from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_strategy_qualification_gate as gate


SOURCE = "a" * 40


def _producer():
    evaluations = [
        {
            "symbol": "BTCUSDT",
            "datasets": {"minute15": {"binding_sha256": "1" * 64}},
            "profiles": [{"profile": "conservative", "net_return_pct": 0.2}],
        },
        {
            "symbol": "ETHUSDT",
            "datasets": {"minute15": {"binding_sha256": "2" * 64}},
            "profiles": [{"profile": "conservative", "net_return_pct": 0.3}],
        },
    ]
    return {
        "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
        "timeframe": "minute15_with_completed_1h_4h",
        "strategy_config": {
            "mechanism": "factory_gen_deep_drawdown_recovery_vwap_reclaim",
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": "3" * 64,
        },
        "config_fingerprint": "4" * 64,
        "evaluations": evaluations,
        "evaluations_digest": gate.digest(evaluations),
    }


def _handoff():
    producer = _producer()
    return {
        "id": "COMPOSITE-QA-" + "5" * 64,
        "task_kind": "composite_runtime_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "required_verifier": "qa-verifier-agent",
        "producer_workflow_run_id": 123456,
        "source_sha": SOURCE,
        "candidate_digest": "6" * 64,
        "requalification_digest": "5" * 64,
        "requalification_verification_digest": "7" * 64,
        "evaluations_digest": producer["evaluations_digest"],
        "runtime_as_of_ms": 1_900_000_000_000,
        "producer": producer,
        "producer_verification": {"decision": "pass"},
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "task_digest": "8" * 64,
    }


def _receipt():
    return {
        "schema_version": "nexus.composite-runtime-qa-receipt.v1",
        "qa_lease_id": "qa-lease",
        "task_digest": "8" * 64,
        "producer_workflow_run_id": 123456,
        "source_sha": SOURCE,
        "candidate_digest": "6" * 64,
        "producer_requalification_digest": "5" * 64,
        "producer_requalification_verification_digest": "7" * 64,
        "evaluations_digest": _producer()["evaluations_digest"],
        "runtime_as_of_ms": 1_900_000_000_000,
        "independent_qa_complete": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "qa_receipt_digest": "9" * 64,
    }


def _manager(status="DONE"):
    row = {
        "id": "COMPOSITE-QA-" + "5" * 64,
        "status": status,
        "authority": 2,
        "qa_verifier_only": True,
        "qa_dispatch_enabled": True,
        "required_verifier": "qa-verifier-agent",
        "qa_handoff_task": _handoff(),
    }
    if status == "DONE":
        row.update(
            assigned_worker="qa-verifier-agent",
            verifier="qa-verifier-agent",
            lease_id="qa-lease",
            verification_evidence=_receipt(),
        )
    return row


@pytest.fixture(autouse=True)
def _verified_upstream(monkeypatch):
    monkeypatch.setattr(gate, "validate_task", lambda value, source: dict(value))
    monkeypatch.setattr(
        gate,
        "verify_receipt",
        lambda receipt, task, **kwargs: (
            receipt.get("qa_receipt_digest") == "9" * 64
            and kwargs.get("lease_id") == "qa-lease"
            and kwargs.get("execution_source_sha") == SOURCE
        ),
    )


def test_done_composite_qa_qualifies_only_for_registry():
    result = gate.evaluate_composite_qualification(_manager())
    assert result["decision"] == "QUALIFIED_FOR_REGISTRY"
    assert result["qualified"] is True
    assert result["registry_admission_allowed"] is True
    assert result["candidate_digest"] == "6" * 64
    assert result["requalification_digest"] == "5" * 64
    assert result["strategy_config_digest"] == gate.digest(result["strategy_config"])
    assert result["runtime_evidence_digest"] == gate.digest(result["runtime_evidence"])
    assert result["registry_mutation_performed"] is False
    assert result["runtime_activation_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    assert gate.verify_composite_qualification(result)["decision"] == "pass"


@pytest.mark.parametrize(
    ("status", "decision"),
    [
        ("VERIFYING", "WAITING_FOR_QA"),
        ("BLOCKED", "REJECTED"),
        ("QUARANTINED", "REJECTED"),
    ],
)
def test_incomplete_or_rejected_composite_qa_never_admits_registry(status, decision):
    result = gate.evaluate_composite_qualification(_manager(status))
    assert result["decision"] == decision
    assert result["qualified"] is False
    assert result["registry_admission_allowed"] is False
    assert result["qa_receipt"] is None
    assert gate.verify_composite_qualification(result)["decision"] == "pass"


def test_self_approval_or_receipt_tamper_fails_closed():
    manager = _manager()
    manager["producer"] = "qa-verifier-agent"
    with pytest.raises(
        gate.CompositeStrategyQualificationError,
        match="authority boundary",
    ):
        gate.evaluate_composite_qualification(manager)

    manager = _manager()
    manager["verification_evidence"]["qa_receipt_digest"] = "0" * 64
    with pytest.raises(
        gate.CompositeStrategyQualificationError,
        match="exact accepted verifier receipt",
    ):
        gate.evaluate_composite_qualification(manager)


def test_redigested_provenance_or_authority_tamper_still_rejects():
    result = gate.evaluate_composite_qualification(_manager())

    provenance = deepcopy(result)
    provenance["candidate_digest"] = "0" * 64
    core = dict(provenance)
    core.pop("qualification_digest", None)
    provenance["qualification_digest"] = gate.digest(core)
    assert gate.verify_composite_qualification(provenance)["decision"] == "reject"

    authority = deepcopy(result)
    authority["runtime_activation_authority"] = True
    core = dict(authority)
    core.pop("qualification_digest", None)
    authority["qualification_digest"] = gate.digest(core)
    assert gate.verify_composite_qualification(authority)["decision"] == "reject"
