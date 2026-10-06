from copy import deepcopy

import pytest

import nexus_composite_val40_contract as contract


def _candidate():
    return {
        "candidate_digest": "a" * 64,
        "research_task_id": "P7-RESEARCH-COMPOSITE-015",
        "source_sha": "b" * 40,
        "mechanism": "factory_gen_example",
        "timeframe": "minute15_with_completed_1h_4h",
        "strategy_config": {
            "mechanism": "factory_gen_example",
            "risk_variant": 0,
            "entry_model": "closed_4h_1h_15m_next_open",
            "factory_contract_digest": "c" * 64,
        },
        "config_fingerprint": "d" * 64,
        "decision": "FORWARD_TO_VAL40",
        "eligible_for_fresh_runtime_requalification": True,
        "requires_fresh_runtime_data": True,
        "paper_only": True,
        "candidate_state_created": False,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def test_contract_is_bounded_and_authority_free(monkeypatch):
    candidate = _candidate()
    verification = {"decision": "pass", "verification_digest": "e" * 64}
    monkeypatch.setattr(contract, "verify_candidate", lambda value: verification)
    value = contract.build_execution_contract(candidate, verification)
    assert value["candidate_digest"] == candidate["candidate_digest"]
    assert value["strategy_config"] == candidate["strategy_config"]
    assert value["qualification_authority"] is False
    assert value["paper_execution_authority"] is False
    assert value["live_trading_authority"] is False
    assert contract.verify_execution_contract(value)["decision"] == "pass"


def test_contract_tamper_or_unverified_candidate_fails_closed(monkeypatch):
    candidate = _candidate()
    verification = {"decision": "pass", "verification_digest": "e" * 64}
    monkeypatch.setattr(contract, "verify_candidate", lambda value: {"decision": "reject"})
    with pytest.raises(contract.CompositeVal40ContractError, match="verification rejected"):
        contract.build_execution_contract(candidate, verification)

    monkeypatch.setattr(contract, "verify_candidate", lambda value: verification)
    value = contract.build_execution_contract(candidate, verification)
    tampered = deepcopy(value)
    tampered["live_trading_authority"] = True
    assert contract.verify_execution_contract(tampered)["decision"] == "reject"
