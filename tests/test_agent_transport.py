from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import agent_manager as am
import agent_transport as at


def task(worker="developer-agent", authority=1, lease_id="lease-1", attempt=1):
    return {
        "id": "T1",
        "title": "bounded task",
        "phase": 4,
        "gate": 11,
        "status": "LEASED",
        "priority": 10,
        "dependencies": [],
        "required_capabilities": [],
        "preferred_resources": [],
        "authority": authority,
        "acceptance": ["verified"],
        "assigned_worker": worker,
        "producer": worker,
        "lease_id": lease_id,
        "attempt": attempt,
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


def result_for(t, *, worker=None, lease=None, correlation=None, dispatch=None, transport=None, outcome="success", evidence=None):
    return {
        "schema_version": 2,
        "task_id": t["id"],
        "lease_id": lease or t["lease_id"],
        "correlation_id": correlation or t.get("correlation_id") or at.correlation_for(t),
        "dispatch_id": dispatch or t.get("dispatch_id") or at.dispatch_id_for(t),
        "worker_id": worker or t["assigned_worker"],
        "transport": transport or t.get("dispatch_transport") or at.transport_for(t["assigned_worker"]),
        "outcome": outcome,
        "evidence": {} if evidence is None else evidence,
    }


def mark_running(t):
    env = at.envelope_for(t)
    t["status"] = "RUNNING"
    t["correlation_id"] = env["correlation_id"]
    t["dispatch_id"] = env["dispatch_id"]
    t["dispatch_transport"] = env["transport"]
    return env


def test_transport_routing_is_explicit():
    assert at.transport_for("developer-agent") == "github-cloud"
    assert at.transport_for("deepseek-bounded") == "deepseek"
    assert at.transport_for("windows-runner") == "windows"


def test_l4_payload_never_dispatches():
    with pytest.raises(ValueError):
        at.envelope_for(task(authority=4))


def test_envelope_binds_stable_task_correlation_and_lease_scoped_dispatch():
    first = task()
    second = task(lease_id="lease-2", attempt=2)
    first_env = at.envelope_for(first)
    second_env = at.envelope_for(second)
    assert first_env["schema_version"] == 2
    assert first_env["correlation_id"] == second_env["correlation_id"]
    assert first_env["dispatch_id"] != second_env["dispatch_id"]
    assert len(first_env["correlation_id"]) == 32
    assert len(first_env["dispatch_id"]) == 32


def test_dispatch_marks_running_only_after_api_accepts(monkeypatch):
    t = task()
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/r")
    calls = []
    monkeypatch.setattr(at, "_api", lambda method, url, payload=None: calls.append((method, url, payload)))
    at.dispatch_task(t, ref="main")
    assert calls and calls[0][0] == "POST"
    assert t["status"] == "RUNNING"
    assert t["dispatch_transport"] == "github-cloud"
    assert t["correlation_id"] == at.correlation_for(t)
    assert t["dispatch_id"] == at.dispatch_id_for(t)


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
    assert "correlation_id" not in t


def test_stale_result_cannot_complete_new_lease():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result_for(t, lease="old-lease"))
    assert t["status"] == "RUNNING"


def test_worker_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError):
        at.ingest_result(cfg, t, result_for(t, worker="qa-verifier-agent"))


def test_correlation_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="correlation"):
        at.ingest_result(cfg, t, result_for(t, correlation="f" * 32))


def test_dispatch_identity_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="dispatch identity"):
        at.ingest_result(cfg, t, result_for(t, dispatch="e" * 32))


def test_transport_spoof_result_is_rejected():
    t = task()
    mark_running(t)
    cfg = config(t)
    with pytest.raises(ValueError, match="transport"):
        at.ingest_result(cfg, t, result_for(t, transport="windows"))


def test_unknown_result_fields_fail_closed():
    t = task()
    mark_running(t)
    cfg = config(t)
    result = result_for(t)
    result["extra"] = "not-allowed"
    with pytest.raises(ValueError, match="schema mismatch"):
        at.ingest_result(cfg, t, result)


def test_valid_result_enters_independent_verification_and_preserves_correlation():
    t = task()
    mark_running(t)
    correlation = t["correlation_id"]
    cfg = config(t)
    at.ingest_result(cfg, t, result_for(t, evidence={"tests": "pass"}))
    assert t["status"] == "VERIFYING"
    assert t["assigned_worker"] == "qa-verifier-agent"
    assert t["verifier"] != t["producer"]
    assert t["correlation_id"] == correlation
    assert at.correlation_for(t) == correlation


def test_result_poll_can_finish_before_stale_lease_triage(monkeypatch):
    t = task()
    mark_running(t)
    cfg = config(t)
    result = result_for(t, evidence={"tests": "pass"})
    monkeypatch.setattr(at, "find_result", lambda lease_id: deepcopy(result))
    assert at.poll_results(cfg) == 1
    assert t["status"] == "VERIFYING"


def test_runtime_worker_preflight_allows_only_bounded_internal_bot_dispatch():
    workflow = Path(".github/workflows/nexus-runtime-worker.yml").read_text(encoding="utf-8")
    preflight = workflow.split("  preflight:\n", 1)[1].split("    runs-on:", 1)[0]
    assert "github.actor == github.repository_owner" in preflight
    assert "github.actor == 'github-actions[bot]'" in preflight
    assert "github.event.inputs.payload_b64 != ''" in preflight
    assert "github.event.inputs.lease_id != ''" in preflight
    assert "github.event.inputs.transport != ''" in preflight

    laptop = workflow.split("  laptop-worker:\n", 1)[1].split("    needs:", 1)[0]
    assert "github.actor == github.repository_owner" in laptop
    assert "github-actions[bot]" not in laptop
