from __future__ import annotations

from copy import deepcopy

import pytest

import agent_manager as am
import agent_transport as at


def task(worker="developer-agent", authority=1):
    return {
        "id": "T1",
        "title": "bounded task",
        "phase": 4,
        "gate": 2,
        "status": "LEASED",
        "priority": 10,
        "dependencies": [],
        "required_capabilities": [],
        "preferred_resources": [],
        "authority": authority,
        "acceptance": ["verified"],
        "assigned_worker": worker,
        "producer": worker,
        "lease_id": "lease-1",
        "attempt": 1,
    }


def config(t):
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4},
        "workers": [
            {"id": "developer-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False},
            {"id": "qa-verifier-agent", "capabilities": [], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": True},
            {"id": "deepseek-bounded", "capabilities": [], "resources": ["deepseek"], "authority_max": 2, "enabled": True, "verifier": False},
            {"id": "windows-runner", "capabilities": [], "resources": ["windows-local"], "authority_max": 3, "enabled": True, "verifier": True},
        ],
        "tasks": [t],
    }


def test_transport_routing_is_explicit():
    assert at.transport_for("developer-agent") == "github-cloud"
    assert at.transport_for("deepseek-bounded") == "deepseek"
    assert at.transport_for("windows-runner") == "windows"


def test_l4_payload_never_dispatches():
    with pytest.raises(ValueError):
        at.envelope_for(task(authority=4))


def test_dispatch_marks_running_only_after_api_accepts(monkeypatch):
    t = task()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    calls = []
    monkeypatch.setattr(at, "_api", lambda method, url, payload=None: calls.append((method, url, payload)))
    at.dispatch_task(t, ref="main")
    assert calls and calls[0][0] == "POST"
    assert t["status"] == "RUNNING"
    assert t["dispatch_transport"] == "github-cloud"
    assert t["dispatch_id"]


def test_api_failure_does_not_fake_running(monkeypatch):
    t = task()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    def fail(*args, **kwargs):
        raise RuntimeError("dispatch failed")
    monkeypatch.setattr(at, "_api", fail)
    with pytest.raises(RuntimeError):
        at.dispatch_task(t, ref="main")
    assert t["status"] == "LEASED"
    assert "dispatch_id" not in t


def test_stale_result_cannot_complete_new_lease():
    t = task()
    t["status"] = "RUNNING"
    t["dispatch_id"] = "d"
    cfg = config(t)
    result = {"schema_version": 1, "task_id": "T1", "lease_id": "old-lease", "worker_id": "developer-agent", "outcome": "success", "evidence": {}}
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result)
    assert t["status"] == "RUNNING"


def test_worker_spoof_result_is_rejected():
    t = task()
    t["status"] = "RUNNING"
    t["dispatch_id"] = "d"
    cfg = config(t)
    result = {"schema_version": 1, "task_id": "T1", "lease_id": "lease-1", "worker_id": "qa-verifier-agent", "outcome": "success", "evidence": {}}
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result)


def test_valid_result_enters_independent_verification():
    t = task()
    t["status"] = "RUNNING"
    t["dispatch_id"] = "d"
    cfg = config(t)
    result = {"schema_version": 1, "task_id": "T1", "lease_id": "lease-1", "worker_id": "developer-agent", "outcome": "success", "evidence": {"tests": "pass"}}
    at.ingest_result(cfg, t, result)
    assert t["status"] == "VERIFYING"
    assert t["assigned_worker"] == "qa-verifier-agent"
    assert t["verifier"] != t["producer"]


def test_result_poll_can_finish_before_stale_lease_triage(monkeypatch):
    t = task()
    t["status"] = "RUNNING"
    t["dispatch_id"] = "d"
    cfg = config(t)
    result = {"schema_version": 1, "task_id": "T1", "lease_id": "lease-1", "worker_id": "developer-agent", "outcome": "success", "evidence": {"tests": "pass"}}
    monkeypatch.setattr(at, "find_result", lambda lease_id: deepcopy(result))
    assert at.poll_results(cfg) == 1
    assert t["status"] == "VERIFYING"
