from copy import deepcopy

import pytest

import nexus_composite_val40_task_materializer as mat


def _candidate(eligible=True):
    return {
        "candidate_digest": "a" * 64,
        "decision": "FORWARD_TO_VAL40" if eligible else "REJECTED_RESEARCH_VALIDATION",
        "eligible_for_fresh_runtime_requalification": eligible,
    }


def _verification(candidate):
    return {
        "decision": "pass",
        "candidate_digest": candidate["candidate_digest"],
        "verification_digest": "b" * 64,
    }


def _contract(candidate):
    return {
        "schema_version": "nexus.composite-val40-execution-contract.v1",
        "candidate_digest": candidate["candidate_digest"],
        "execution_contract_digest": "c" * 64,
    }


def test_materializes_only_verified_forward_candidate(monkeypatch):
    candidate = _candidate(True)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    monkeypatch.setattr(mat, "build_execution_contract", lambda c, v: _contract(c))
    monkeypatch.setattr(mat, "verify_execution_contract", lambda value: {"decision": "pass"})
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    task = result["tasks"][0]
    assert task["id"] == "COMPOSITE-VAL40-" + "a" * 64
    assert task["status"] == "READY"
    assert task["required_producer"] == "research-agent"
    assert task["required_verifier"] == "qa-verifier-agent"
    assert task["composite_val40_execution_contract"]["candidate_digest"] == "a" * 64
    assert task["authority"] == 2
    assert task["paper_execution_authority"] is False
    assert task["live_trading_authority"] is False
    assert mat.materialize_candidate_tasks(result, candidate, verification) == result


def test_rejected_candidate_remains_evidence_only(monkeypatch):
    candidate = _candidate(False)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    assert result["tasks"] == []


def test_tamper_contract_or_collision_fails_closed(monkeypatch):
    candidate = _candidate(True)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    monkeypatch.setattr(mat, "build_execution_contract", lambda c, v: _contract(c))
    monkeypatch.setattr(mat, "verify_execution_contract", lambda value: {"decision": "reject"})
    with pytest.raises(mat.CompositeVal40MaterializerError, match="execution contract rejected"):
        mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)

    monkeypatch.setattr(mat, "verify_execution_contract", lambda value: {"decision": "pass"})
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    collision = deepcopy(result)
    collision["tasks"][0]["authority"] = 3
    with pytest.raises(mat.CompositeVal40MaterializerError, match="collision"):
        mat.materialize_candidate_tasks(collision, candidate, verification)
