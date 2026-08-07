import urllib.error

import fast_agent_orchestrator as fao
from fast_agent_orchestrator import (
    authoritative_retry_evidence,
    classify,
    newest_by_name,
    retry_eligibility,
)


def test_classify_states():
    assert classify({"status": "in_progress", "conclusion": None}) == "RUNNING"
    assert classify({"status": "waiting", "conclusion": None}) == "WAITING"
    assert classify({"status": "completed", "conclusion": "action_required"}) == "WAITING"
    assert classify({"status": "completed", "conclusion": "success"}) == "DONE"
    assert classify({"status": "completed", "conclusion": "failure"}) == "FAILED"
    assert classify({"status": "completed", "conclusion": "cancelled"}) == "BLOCKED"


def test_newest_by_name_keeps_first_seen():
    runs = [
        {"name": "CI", "databaseId": 2},
        {"name": "CI", "databaseId": 1},
        {"name": "Data", "databaseId": 3},
    ]
    latest = newest_by_name(runs)
    assert latest["CI"]["databaseId"] == 2
    assert latest["Data"]["databaseId"] == 3


def transient_run(**overrides):
    run = {
        "databaseId": 101,
        "name": "Test",
        "status": "completed",
        "conclusion": "timed_out",
        "headSha": "abc123",
        "attempt": 1,
        "updatedAt": "2026-08-07T10:00:00Z",
        "url": "https://example.invalid/run/101",
    }
    run.update(overrides)
    return run


def test_retry_eligibility_requires_first_attempt_and_complete_identity():
    assert retry_eligibility(transient_run()) == (
        True,
        "eligible_first_attempt_transient_failure",
    )
    assert retry_eligibility(transient_run(attempt=2)) == (False, "already_retried")
    assert retry_eligibility(transient_run(attempt=None)) == (
        False,
        "retry_history_unavailable",
    )
    assert retry_eligibility(transient_run(headSha=None)) == (False, "missing_head_sha")


def test_deterministic_or_ambiguous_failure_is_not_auto_retried():
    assert retry_eligibility(transient_run(conclusion="failure")) == (
        False,
        "non_retryable_or_ambiguous_failure",
    )
    assert retry_eligibility(transient_run(conclusion="cancelled")) == (False, "not_failed")


def test_coordinator_never_retries_itself():
    assert retry_eligibility(transient_run(name=fao.COORDINATOR_WORKFLOW)) == (
        False,
        "coordinator_self_observation",
    )


def test_authoritative_evidence_rejects_stale_or_out_of_order_listing():
    listed = transient_run()
    assert authoritative_retry_evidence(listed, transient_run(attempt=2)) == (
        False,
        "already_retried",
    )
    assert authoritative_retry_evidence(listed, transient_run(headSha="newsha")) == (
        False,
        "run_identity_changed:headSha",
    )
    assert authoritative_retry_evidence(listed, transient_run(databaseId=999)) == (
        False,
        "run_identity_changed:databaseId",
    )


def test_two_fresh_coordinators_cannot_retry_after_authoritative_attempt_advances(monkeypatch, tmp_path):
    fao.STATE_DIR = tmp_path / "state"
    fao.STATE_FILE = fao.STATE_DIR / "status.json"
    fao.EVENT_FILE = fao.STATE_DIR / "events.jsonl"
    fao.HEARTBEAT_FILE = fao.STATE_DIR / "heartbeat.json"

    listed = transient_run()
    monkeypatch.setattr(fao, "get_runs", lambda: [listed])
    monkeypatch.setattr(fao, "gh_available", lambda: True)

    attempts = iter([transient_run(attempt=1), transient_run(attempt=2)])
    monkeypatch.setattr(fao, "get_run_details", lambda _run_id: next(attempts))
    reruns = []
    monkeypatch.setattr(fao, "rerun_failed", lambda run_id: (reruns.append(run_id) or True, "ok"))

    first = fao.inspect_once({}, auto_retry=True)
    second = fao.inspect_once({}, auto_retry=True)

    assert reruns == [101]
    assert first["workflows"]["Test"]["auto_retry"]["attempted"] is True
    assert second["workflows"]["Test"]["auto_retry"]["attempted"] is False
    assert second["workflows"]["Test"]["auto_retry"]["reason"] == "already_retried"


def test_authoritative_history_failure_fails_closed(monkeypatch, tmp_path):
    fao.STATE_DIR = tmp_path / "state"
    fao.STATE_FILE = fao.STATE_DIR / "status.json"
    fao.EVENT_FILE = fao.STATE_DIR / "events.jsonl"
    fao.HEARTBEAT_FILE = fao.STATE_DIR / "heartbeat.json"

    monkeypatch.setattr(fao, "get_runs", lambda: [transient_run()])
    monkeypatch.setattr(fao, "gh_available", lambda: True)
    monkeypatch.setattr(
        fao,
        "get_run_details",
        lambda _run_id: (_ for _ in ()).throw(urllib.error.URLError("network down")),
    )
    reruns = []
    monkeypatch.setattr(fao, "rerun_failed", lambda run_id: (reruns.append(run_id) or True, "ok"))

    result = fao.inspect_once({}, auto_retry=True)

    assert reruns == []
    retry = result["workflows"]["Test"]["auto_retry"]
    assert retry["attempted"] is False
    assert retry["reason"] == "authoritative_history_unavailable"
