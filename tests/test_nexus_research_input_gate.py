"""Source-exact Research Agent input readiness and bounded first-cache-race recovery."""
from __future__ import annotations

import agent_transport
import agent_manager_runner as gate

SOURCE = "a" * 40
REPO = "saladinayoubi1/lbank-research-automation"


def _task(**override):
    return {
        "id": gate.RESEARCH_TASK, "status": "PENDING", "attempt": 0,
        "assigned_worker": None, "failure_evidence": None,
        "research_cache_recovery_count": 0, **override,
    }


def _ctx(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
    monkeypatch.setenv("GITHUB_SHA", SOURCE)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GH_TOKEN", "test-mocked-do-not-call-network")


def _initial_failure(**overrides):
    row = {
        "status": "TRIAGE",
        "attempt": 1,
        "lease_id": "first-lease",
        "assigned_worker": "research-agent",
        "producer": "research-agent",
        "failure_class": "verified_research_execution_failed",
        "failure_evidence": {
            "executor": "nexus-real-composite-backtest",
            "reason": gate.RESEARCH_FIRST_MISS,
            "auto_demo_promotion": False, "live_enabled": False,
        },
        "dispatch_id": "first-dispatch",
        "external_wait_state": "WAITING_EXTERNAL",
    }
    row.update(overrides)
    return {"tasks": [_task(**row)]}


def test_missing_input_parks_only_research_not_other_tasks(monkeypatch):
    monkeypatch.setattr(gate.am, "emit", lambda *a, **k: None)
    other = {"id": "P4-DATA-001", "status": "READY"}
    conf = {"tasks": [_task(), other]}
    assert gate.apply_research_input_gate(conf, ready=False) == "parked_waiting_cache"
    assert conf["tasks"][0]["status"] == "BLOCKED"
    assert conf["tasks"][0]["blocked_reason"] == gate.RESEARCH_WAIT
    assert conf["tasks"][1] == other
    assert gate.apply_research_input_gate(conf, ready=False) == "wait_unchanged"
    assert gate.apply_research_input_gate(conf, ready=True) == "ready_for_producer_lease"
    assert conf["tasks"][0]["status"] == "READY"
    assert conf["tasks"][0]["research_cache_recovery_count"] == 0


def test_first_observed_cache_race_recovers_once_with_audit_preserved(monkeypatch):
    monkeypatch.setattr(gate.am, "emit", lambda *a, **k: None)
    conf = _initial_failure()
    prior = dict(conf["tasks"][0]["failure_evidence"])
    assert gate.apply_research_input_gate(conf, ready=False) == "wait_unchanged"
    task = conf["tasks"][0]
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == gate.RESEARCH_WAIT
    assert task["attempt"] == 1
    assert task["research_cache_recovery_count"] == 1
    assert task["failure_evidence"] == prior
    assert task["research_cache_race_evidence"]["first_failure"] == prior
    assert task["lease_id"] is None
    assert task["dispatch_id"] is None
    assert gate.apply_research_input_gate(conf, ready=False) == "wait_unchanged"
    assert gate.apply_research_input_gate(conf, ready=True) == "ready_for_producer_lease"
    assert task["status"] == "READY"
    assert task["research_cache_recovery_count"] == 1
    assert gate._observed_initial_cache_race(task) is False


def test_inflight_root_cause_lease_abandoned_only_for_exact_observed_first_race(monkeypatch):
    monkeypatch.setattr(gate.am, "emit", lambda *a, **k: None)
    conf = _initial_failure(
        status="RUNNING", triage_mode="root_cause_first",
        assigned_worker="architect-agent", lease_id="unneeded-rca-lease",
    )
    assert gate.apply_research_input_gate(conf, ready=True) == "ready_for_producer_lease"
    task = conf["tasks"][0]
    assert task["status"] == "READY"
    assert task["assigned_worker"] is None
    assert task["lease_id"] is None
    assert task["research_cache_race_evidence"]["first_failure"]["reason"] == gate.RESEARCH_FIRST_MISS


def test_never_retry_second_failure_or_unrelated_defect(monkeypatch):
    monkeypatch.setattr(gate.am, "emit", lambda *a, **k: None)
    for wrong in [
        {"attempt": 2},
        {"failure_evidence": {"executor": "nexus-real-composite-backtest", "reason": "digest mismatch", "auto_demo_promotion": False, "live_enabled": False}},
        {"research_cache_recovery_count": 1},
        {"failure_class": "adversarial_data_corruption"},
    ]:
        conf = _initial_failure(**wrong)
        assert gate.apply_research_input_gate(conf, ready=True) == "ready_no_change"
        assert conf["tasks"][0]["status"] == "TRIAGE"
    unrelated = {"tasks": [_task(status="BLOCKED", blocked_reason="independent verifier unavailable")]}
    assert gate.apply_research_input_gate(unrelated, ready=True) == "ready_no_change"
    assert unrelated["tasks"][0]["status"] == "BLOCKED"


def test_no_l4_or_done_task_is_mutated(monkeypatch):
    monkeypatch.setattr(gate.am, "emit", lambda *a, **k: None)
    for status in ("DONE", "QUARANTINED", "OWNER_REQUIRED"):
        conf = {"tasks": [_task(status=status)]}
        assert gate.apply_research_input_gate(conf, ready=False) == "terminal_unchanged"
        assert conf["tasks"][0]["status"] == status


def test_source_and_branch_match_required_for_metadata_readiness(monkeypatch):
    _ctx(monkeypatch)
    conf = {"tasks": [_task()]}
    seen = []
    def api(method, url, payload=None):
        seen.append((method, url))
        return {"actions_caches": [
            {"key": gate.RESEARCH_BOOTSTRAP_CACHE_PREFIX + SOURCE,
             "ref": "refs/heads/main", "size_in_bytes": 40000}
        ]}
    monkeypatch.setattr(agent_transport, "_api", api)
    assert gate.research_cache_status(conf) == (True, "source_exact_transport_cache_present")
    assert seen and "ref=refs%2Fheads%2Fmain" in seen[0][1]
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    assert gate.research_cache_status(conf) == (False, "not_on_authorized_main_with_token")
    assert len(seen) == 1


def test_cache_metadata_rejects_wrong_source_zero_length_or_wrong_ref(monkeypatch):
    _ctx(monkeypatch)
    conf = {"tasks": [_task()]}
    monkeypatch.setattr(agent_transport, "_api", lambda *a, **kw: {
        "actions_caches": [
            {"key": gate.RESEARCH_BOOTSTRAP_CACHE_PREFIX + SOURCE, "ref": "refs/pull/33/merge", "size_in_bytes": 4000},
            {"key": gate.RESEARCH_CACHE_PREFIX + ("b" * 40), "ref": "refs/heads/main", "size_in_bytes": 4000},
            {"key": gate.RESEARCH_BOOTSTRAP_CACHE_PREFIX + SOURCE, "ref": "refs/heads/main", "size_in_bytes": 0},
        ],
    })
    assert gate.research_cache_status(conf) == (False, "source_exact_transport_cache_absent")
    def deny(*a, **kw):
        raise RuntimeError("temporary GitHub API unavailable")
    monkeypatch.setattr(agent_transport, "_api", deny)
    ready, reason = gate.research_cache_status(conf)
    assert not ready and reason.startswith("source_exact_cache_metadata_unavailable")


def test_successor_cache_requires_exact_qa_attested_ledger_digest(monkeypatch):
    _ctx(monkeypatch)
    digest = "c" * 64
    conf = {
        "tasks": [
            _task(status="DONE"),
            {
                "id": gate.SECOND,
                "status": "BLOCKED",
                "research_predecessor_ledger_digest": digest,
            },
        ],
    }
    seen = []

    def api(method, url, payload=None):
        seen.append(url)
        return {
            "actions_caches": [
                {
                    "key": gate.RESEARCH_CACHE_PREFIX + SOURCE + "-" + digest,
                    "ref": "refs/heads/main",
                    "size_in_bytes": 40000,
                },
                {
                    "key": gate.RESEARCH_CACHE_PREFIX + SOURCE + "-" + ("d" * 64),
                    "ref": "refs/heads/main",
                    "size_in_bytes": 40000,
                },
            ]
        }

    monkeypatch.setattr(agent_transport, "_api", api)
    assert gate.research_cache_status(conf) == (True, "source_exact_transport_cache_present")
    assert digest in seen[0]


def test_successor_cache_rejects_same_source_with_stale_ledger(monkeypatch):
    _ctx(monkeypatch)
    digest = "c" * 64
    conf = {
        "tasks": [
            _task(status="DONE"),
            {
                "id": gate.SECOND,
                "status": "BLOCKED",
                "research_predecessor_ledger_digest": digest,
            },
        ],
    }
    monkeypatch.setattr(agent_transport, "_api", lambda *a, **kw: {
        "actions_caches": [
            {
                "key": gate.RESEARCH_CACHE_PREFIX + SOURCE + "-" + ("d" * 64),
                "ref": "refs/heads/main",
                "size_in_bytes": 40000,
            }
        ]
    })
    assert gate.research_cache_status(conf) == (False, "source_exact_transport_cache_absent")


def test_existing_source_exact_running_workflow_prevents_duplicate_dispatch(monkeypatch):
    _ctx(monkeypatch)
    calls = []
    def api(method, url, payload=None):
        calls.append(method)
        return {"workflow_runs": [
            {"head_sha": SOURCE, "head_branch": "main", "event": "push", "status": "in_progress"}
        ]}
    monkeypatch.setattr(agent_transport, "_api", api)
    conf = {"tasks": [_task(status="BLOCKED", blocked_reason=gate.RESEARCH_WAIT)]}
    assert gate.request_missing_research_cache(conf, "source_exact_transport_cache_absent") == "matching_research_workflow_already_running"
    assert calls == ["GET"]
    assert conf["tasks"][0]["research_cache_requested_sha"] == SOURCE


def test_missing_source_exact_workflow_is_dispatched_once_without_blind_repeat(monkeypatch):
    _ctx(monkeypatch)
    events = []
    monkeypatch.setattr(gate.am, "emit", lambda *a, **kw: events.append(kw))
    calls = []
    def api(method, url, payload=None):
        calls.append((method, url, payload))
        if method == "GET":
            return {"workflow_runs": [{"head_sha": "b" * 40, "head_branch": "main", "event": "push", "status": "completed", "conclusion": "success"}]}
        assert payload == {"ref": "main"}
        return None
    monkeypatch.setattr(agent_transport, "_api", api)
    conf = {"tasks": [_task(status="BLOCKED", blocked_reason=gate.RESEARCH_WAIT)]}
    assert gate.request_missing_research_cache(conf, "source_exact_transport_cache_absent") == "source_exact_cache_build_dispatched"
    assert [c[0] for c in calls] == ["GET", "POST"]
    assert conf["tasks"][0]["research_cache_requested_sha"] == SOURCE
    assert gate.request_missing_research_cache(conf, "source_exact_transport_cache_absent") == "prior_dispatch_pending_no_duplicate"
    assert [c[0] for c in calls] == ["GET", "POST", "GET"]


def test_success_or_failure_without_cache_never_blind_dispatches(monkeypatch):
    _ctx(monkeypatch)
    for conclusion, expected in [
        ("success", "successful_workflow_cache_pending_or_missing"),
        ("failure", "matching_research_workflow_failed_review_required"),
    ]:
        calls = []
        def api(method, url, payload=None):
            calls.append(method)
            return {"workflow_runs": [
                {"head_sha": SOURCE, "head_branch": "main", "event": "push", "status": "completed", "conclusion": conclusion}
            ]}
        monkeypatch.setattr(agent_transport, "_api", api)
        conf = {"tasks": [_task(status="BLOCKED", blocked_reason=gate.RESEARCH_WAIT)]}
        assert gate.request_missing_research_cache(conf, "source_exact_transport_cache_absent") == expected
        assert calls == ["GET"]
