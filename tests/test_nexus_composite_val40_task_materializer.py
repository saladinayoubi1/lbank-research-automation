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
    return {"decision": "pass", "candidate_digest": candidate["candidate_digest"]}


def test_materializes_only_verified_forward_candidate(monkeypatch):
    candidate = _candidate(True)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    assert len(result["tasks"]) == 1
    task = result["tasks"][0]
    assert task["id"] == "COMPOSITE-VAL40-" + "a" * 64
    assert task["status"] == "READY"
    assert task["required_producer"] == "research-agent"
    assert task["required_verifier"] == "qa-verifier-agent"
    assert task["authority"] == 2
    assert task["paper_execution_authority"] is False
    assert task["live_trading_authority"] is False

    again = mat.materialize_candidate_tasks(result, candidate, verification)
    assert again == result


def test_rejected_candidate_remains_evidence_only(monkeypatch):
    candidate = _candidate(False)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    assert result["tasks"] == []


def test_tamper_or_collision_fails_closed(monkeypatch):
    candidate = _candidate(True)
    verification = _verification(candidate)
    monkeypatch.setattr(mat, "verify_candidate", lambda value: {"decision": "reject"})
    with pytest.raises(mat.CompositeVal40MaterializerError, match="verification rejected"):
        mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)

    monkeypatch.setattr(mat, "verify_candidate", lambda value: verification)
    result = mat.materialize_candidate_tasks({"tasks": []}, candidate, verification)
    collision = deepcopy(result)
    collision["tasks"][0]["authority"] = 3
    with pytest.raises(mat.CompositeVal40MaterializerError, match="collision"):
        mat.materialize_candidate_tasks(collision, candidate, verification)
