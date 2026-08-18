from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import agent_manager as am
import agent_manager_runner as runner
import agent_transport as transport


NOW = datetime(2026, 8, 18, 14, 30, tzinfo=timezone.utc)


def _task(task_id: str, capability: str, *, status: str = "READY", priority: int = 10) -> dict:
    return {
        "id": task_id,
        "title": task_id,
        "phase": 7,
        "gate": 0,
        "status": status,
        "priority": priority,
        "dependencies": [],
        "required_capabilities": [capability],
        "preferred_resources": [],
        "authority": 1,
        "acceptance": [],
    }


def test_dynamic_routing_uses_runtime_metrics_and_persists_candidate_evidence():
    config = {
        "schema_version": 1,
        "phase": 7,
        "policy": {"max_parallel_tasks": 2},
        "resource_metrics": {
            "worker-slow": {
                "available": True,
                "health_score": 0.45,
                "latency_ms": 2400,
                "failure_rate": 0.25,
                "cost_units": 2.0,
            },
            "worker-fast": {
                "available": True,
                "health_score": 0.99,
                "latency_ms": 40,
                "failure_rate": 0.01,
                "cost_units": 0.5,
            },
            "worker-down": {
                "available": False,
                "health_score": 0.0,
                "latency_ms": 0,
                "failure_rate": 0,
                "cost_units": 0,
            },
        },
        "workers": [
            {"id": "worker-slow", "capabilities": ["compute"], "resources": ["cloud"], "authority_max": 2},
            {"id": "worker-fast", "capabilities": ["compute"], "resources": ["cloud"], "authority_max": 2},
            {"id": "worker-down", "capabilities": ["compute"], "resources": ["cloud"], "authority_max": 2},
        ],
        "tasks": [_task("T1", "compute")],
    }

    am.validate_config(config)
    am.assign_ready_tasks(config, NOW)

    task = config["tasks"][0]
    decision = task["routing_decision"]
    assert task["assigned_worker"] == "worker-fast"
    assert decision["selected_worker"] == "worker-fast"
    by_worker = {row["worker_id"]: row for row in decision["candidates"]}
    assert by_worker["worker-fast"]["selection_reason"] == "highest_deterministic_score"
    assert by_worker["worker-slow"]["selection_reason"] == "lower_score_than_selected"
    assert by_worker["worker-down"]["eligible"] is False
    assert "unavailable" in by_worker["worker-down"]["rejection_reasons"]
    assert by_worker["worker-fast"]["observed"]["latency_ms"] == 40.0


def test_budget_locality_and_trust_fail_closed_with_durable_reasons():
    task = _task("T1", "compute")
    task.update(
        {
            "required_resources": ["cloud"],
            "required_data_locality": ["canonical-dataset-a"],
            "required_trust_domain": "trusted-research",
            "max_cost_units": 1.0,
        }
    )
    config = {
        "schema_version": 1,
        "phase": 7,
        "policy": {"max_parallel_tasks": 1},
        "workers": [
            {
                "id": "wrong",
                "capabilities": ["compute"],
                "resources": ["cloud"],
                "authority_max": 2,
                "routing": {
                    "cost_units": 2.0,
                    "data_locality": ["other-dataset"],
                    "trust_domains": ["untrusted"],
                },
            }
        ],
        "tasks": [task],
    }

    am.validate_config(config)
    am.assign_ready_tasks(config, NOW)

    assert task["status"] == "READY"
    assert task["routing_decision"]["selected_worker"] is None
    reasons = task["routing_decision"]["candidates"][0]["rejection_reasons"]
    assert "cost_budget_exceeded" in reasons
    assert "required_data_not_local" in reasons
    assert "trust_domain_mismatch" in reasons


def test_external_wait_dispatch_allows_independent_zero_idle_assignment(monkeypatch):
    task_a = _task("A", "external", status="LEASED", priority=100)
    task_a.update(
        {
            "assigned_worker": "cloud-a",
            "producer": "cloud-a",
            "lease_id": "lease-a",
            "attempt": 1,
            "leased_at": am.iso(NOW),
            "heartbeat_at": am.iso(NOW),
            "lease_expires_at": am.iso(NOW + am.timedelta(minutes=5)),
        }
    )
    task_b = _task("B", "local", status="READY", priority=90)
    config = {
        "schema_version": 1,
        "phase": 7,
        "policy": {"max_parallel_tasks": 3, "offline_courier_workers": []},
        "workers": [
            {"id": "cloud-a", "capabilities": ["external"], "resources": ["github-cloud"], "authority_max": 2},
            {"id": "worker-b", "capabilities": ["local"], "resources": ["agent"], "authority_max": 2},
            {
                "id": "verifier",
                "capabilities": ["external"],
                "resources": ["github-cloud"],
                "authority_max": 2,
                "verifier": True,
            },
        ],
        "tasks": [task_a, task_b],
    }
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(transport, "_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(am, "utcnow", lambda: NOW)

    transport.dispatch_task(task_a, ref="main")

    assert task_a["status"] == "RUNNING"
    assert task_a["external_wait_state"] == am.WAITING_EXTERNAL
    assert task_a["waiting_from_status"] == "LEASED"
    assert task_a["external_wait_timeline"][0]["dispatch_id"] == task_a["dispatch_id"]

    am.assign_ready_tasks(config, NOW + am.timedelta(seconds=1))

    assert task_b["assigned_worker"] == "worker-b"
    overlap = task_b["zero_idle_evidence"]["overlapped_external_waits"]
    assert [row["task_id"] for row in overlap] == ["A"]
    assert overlap[0]["wait_started_at"] == task_a["external_wait_started_at"]
    summary = am.summarize(config)
    assert summary["external_waiting"][0]["task_id"] == "A"
    assert summary["zero_idle_assignments"][0]["task_id"] == "B"


def test_result_from_external_wait_enters_independent_verification(monkeypatch):
    task = _task("A", "external", status="LEASED")
    task.update(
        {
            "assigned_worker": "producer",
            "producer": "producer",
            "lease_id": "lease-a",
            "attempt": 1,
            "leased_at": am.iso(NOW),
            "heartbeat_at": am.iso(NOW),
            "lease_expires_at": am.iso(NOW + am.timedelta(minutes=5)),
        }
    )
    config = {
        "schema_version": 1,
        "phase": 7,
        "policy": {"max_parallel_tasks": 3, "offline_courier_workers": []},
        "workers": [
            {"id": "producer", "capabilities": ["external"], "resources": ["github-cloud"], "authority_max": 2},
            {
                "id": "verifier",
                "capabilities": ["external"],
                "resources": ["github-cloud"],
                "authority_max": 2,
                "verifier": True,
            },
        ],
        "tasks": [task],
    }
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setattr(transport, "_api", lambda *args, **kwargs: None)
    monkeypatch.setattr(am, "utcnow", lambda: NOW)

    transport.dispatch_task(task, ref="main")
    result = {
        "schema_version": 2,
        "task_id": task["id"],
        "lease_id": task["lease_id"],
        "correlation_id": task["correlation_id"],
        "dispatch_id": task["dispatch_id"],
        "worker_id": "producer",
        "transport": "github-cloud",
        "outcome": "success",
        "evidence": {"sha256": "abc"},
    }
    transport.ingest_result(config, task, result)

    assert task["status"] == "VERIFYING"
    assert task["assigned_worker"] == "verifier"
    assert task["producer"] == "producer"
    assert task["external_wait_state"] == "COMPLETED"
    assert task["external_wait_completed_at"] is not None
    assert task["external_wait_timeline"][-1]["outcome"] == "success"


def test_runtime_merge_preserves_resource_metrics_routing_and_wait_evidence():
    template = {
        "schema_version": 1,
        "phase": 7,
        "policy": {"max_parallel_tasks": 2},
        "workers": [{"id": "worker", "capabilities": ["compute"], "resources": ["cloud"], "authority_max": 2}],
        "tasks": [_task("T1", "compute")],
    }
    runtime = deepcopy(template)
    runtime["resource_metrics"] = {"worker": {"available": True, "latency_ms": 22.0}}
    runtime["resource_metrics_updated_at"] = "2026-08-18T14:00:00+00:00"
    runtime["tasks"][0].update(
        {
            "status": "RUNNING",
            "external_wait_state": am.WAITING_EXTERNAL,
            "assigned_worker": "worker",
            "producer": "worker",
            "lease_id": "lease-1",
            "routing_decision": {"selected_worker": "worker"},
            "waiting_from_status": "LEASED",
            "external_wait_started_at": "2026-08-18T14:01:00+00:00",
            "external_wait_timeline": [{"started_at": "2026-08-18T14:01:00+00:00"}],
            "zero_idle_evidence": {"overlapped_external_waits": []},
        }
    )

    merged = runner.merge_definition(template, runtime)

    assert merged["resource_metrics"]["worker"]["latency_ms"] == 22.0
    assert merged["resource_metrics_updated_at"] == runtime["resource_metrics_updated_at"]
    assert merged["tasks"][0]["routing_decision"]["selected_worker"] == "worker"
    assert merged["tasks"][0]["status"] == "RUNNING"
    assert merged["tasks"][0]["external_wait_state"] == am.WAITING_EXTERNAL
    assert merged["tasks"][0]["external_wait_timeline"]
