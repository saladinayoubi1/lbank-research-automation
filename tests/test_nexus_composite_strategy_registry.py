from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_strategy_qualification_gate as gate
from strategy_registry import (
    StrategyRegistryError,
    _digest,
    build_composite_qualified_strategy_record,
    verify_composite_qualified_strategy_record,
)


SOURCE = "a" * 40


def _qualification(monkeypatch):
    evaluations = [
        {"symbol": "BTCUSDT", "profiles": [{"profile": "stress", "net_return_pct": 0.1}]},
        {"symbol": "ETHUSDT", "profiles": [{"profile": "stress", "net_return_pct": 0.2}]},
    ]
    producer = {
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
    task = {
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
    receipt = {
        "qa_receipt_digest": "9" * 64,
        "independent_qa_complete": True,
    }
    manager = {
        "id": task["id"],
        "status": "DONE",
        "authority": 2,
        "qa_verifier_only": True,
        "qa_dispatch_enabled": True,
        "required_verifier": "qa-verifier-agent",
        "qa_handoff_task": task,
        "assigned_worker": "qa-verifier-agent",
        "verifier": "qa-verifier-agent",
        "lease_id": "qa-lease",
        "verification_evidence": receipt,
    }
    monkeypatch.setattr(gate, "validate_task", lambda value, source: dict(value))
    monkeypatch.setattr(gate, "verify_receipt", lambda receipt, task, **kwargs: True)
    qualification = gate.evaluate_composite_qualification(manager)
    verification = gate.verify_composite_qualification(qualification)
    assert verification["decision"] == "pass"
    return qualification, verification


def test_composite_reg50_record_is_immutable_qualified_candidate_only(monkeypatch):
    qualification, verification = _qualification(monkeypatch)
    record = build_composite_qualified_strategy_record(qualification, verification)
    assert record["schema_version"] == "nexus.composite-strategy-registry-record.v1"
    assert record["system_map_node"] == "REG-50"
    assert record["origin_kind"] == "composite_mechanism"
    assert record["family"] == "composite_mechanism"
    assert record["mechanism"] == qualification["mechanism"]
    assert record["variant_id"] == qualification["config_fingerprint"]
    assert record["lifecycle_state"] == "QUALIFIED_CANDIDATE"
    assert record["demo_matrix_member"] is False
    assert record["runtime_activation_authority"] is False
    assert record["paper_execution_authority"] is False
    assert record["automatic_strategy_promotion"] is False
    assert record["live_execution_allowed"] is False
    assert verify_composite_qualified_strategy_record(record)["decision"] == "pass"


def test_composite_reg50_rejects_waiting_or_stale_qualification(monkeypatch):
    qualification, verification = _qualification(monkeypatch)

    waiting = deepcopy(qualification)
    waiting["decision"] = "WAITING_FOR_QA"
    with pytest.raises(StrategyRegistryError, match="verification"):
        build_composite_qualified_strategy_record(waiting, verification)

    stale = deepcopy(verification)
    stale["verification_digest"] = "0" * 64
    with pytest.raises(StrategyRegistryError, match="verification"):
        build_composite_qualified_strategy_record(qualification, stale)


def test_composite_reg50_redigested_identity_or_activation_tamper_rejects(monkeypatch):
    qualification, verification = _qualification(monkeypatch)
    record = build_composite_qualified_strategy_record(qualification, verification)

    identity = deepcopy(record)
    identity["mechanism"] = "forged_mechanism"
    core = dict(identity)
    core.pop("record_digest", None)
    identity["record_digest"] = _digest(core)
    assert verify_composite_qualified_strategy_record(identity)["decision"] == "reject"

    activation = deepcopy(record)
    activation["demo_matrix_member"] = True
    core = dict(activation)
    core.pop("record_digest", None)
    activation["record_digest"] = _digest(core)
    assert verify_composite_qualified_strategy_record(activation)["decision"] == "reject"

    provenance = deepcopy(record)
    provenance["candidate_digest"] = "0" * 64
    core = dict(provenance)
    core.pop("record_digest", None)
    provenance["record_digest"] = _digest(core)
    assert verify_composite_qualified_strategy_record(provenance)["decision"] == "reject"
