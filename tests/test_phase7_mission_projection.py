from __future__ import annotations

import json
from pathlib import Path

from product_mission_runtime import ProductMissionRuntime


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _config() -> dict:
    return {
        "schema_version": 1,
        "phase": 7,
        "policy": {"l4_owner_required": True},
        "workers": [
            {
                "id": "cloud-a",
                "capabilities": ["research"],
                "resources": ["github-cloud"],
                "authority_max": 2,
                "enabled": True,
                "routing": {"health_score": 0.8, "latency_ms": 200},
            },
            {
                "id": "agent-b",
                "capabilities": ["local_compute"],
                "resources": ["agent"],
                "authority_max": 2,
                "enabled": True,
            },
        ],
        "tasks": [
            {
                "id": "A", "title": "External research", "phase": 7, "gate": 0,
                "status": "PENDING", "priority": 100, "dependencies": [],
                "required_capabilities": ["research"], "preferred_resources": ["github-cloud"],
                "authority": 1, "acceptance": ["verified"],
            },
            {
                "id": "B", "title": "Independent local work", "phase": 7, "gate": 0,
                "status": "PENDING", "priority": 90, "dependencies": [],
                "required_capabilities": ["local_compute"], "preferred_resources": ["agent"],
                "authority": 1, "acceptance": ["verified"],
            },
        ],
    }


def test_mission_control_projects_real_routing_wait_and_zero_idle_evidence(tmp_path: Path) -> None:
    config = _config()
    config_path = tmp_path / "config.json"
    _write(config_path, config)
    runtime = json.loads(json.dumps(config))
    runtime["resource_metrics"] = {
        "cloud-a": {"available": True, "health_score": 0.97, "latency_ms": 45, "failure_rate": 0.01, "cost_units": 0.2},
        "agent-b": {"available": True, "health_score": 0.99, "latency_ms": 5, "failure_rate": 0.0, "cost_units": 0.0},
    }
    runtime["tasks"][0].update({
        "status": "RUNNING",
        "assigned_worker": "cloud-a",
        "producer": "cloud-a",
        "lease_id": "lease-a",
        "fence_generation": 4,
        "active_attempt_id": "attempt-a-4",
        "correlation_id": "corr-a",
        "dispatch_id": "dispatch-a",
        "dispatch_transport": "github-cloud",
        "external_wait_state": "WAITING_EXTERNAL",
        "waiting_from_status": "LEASED",
        "external_wait_started_at": "2026-08-18T14:50:00Z",
        "external_wait_timeline": [{
            "started_at": "2026-08-18T14:50:00Z", "from_status": "LEASED",
            "dispatch_id": "dispatch-a", "worker_id": "cloud-a", "transport": "github-cloud",
        }],
        "routing_decision": {
            "evaluated_at": "2026-08-18T14:49:59Z",
            "selected_worker": "cloud-a",
            "selected_score": 41.5,
            "reason": "highest_deterministic_score",
            "secret_key": "MUST_NOT_PROJECT",
            "candidates": [{
                "worker_id": "cloud-a", "eligible": True, "score": 41.5,
                "selection_reason": "highest_deterministic_score",
                "rejection_reasons": [],
                "components": {"health": 29.1, "cost": -1.0},
                "observed": {"available": True, "health_score": 0.97, "latency_ms": 45, "private_token": "MUST_NOT_PROJECT"},
                "api_secret": "MUST_NOT_PROJECT",
            }],
        },
    })
    runtime["tasks"][1].update({
        "status": "LEASED",
        "assigned_worker": "agent-b",
        "producer": "agent-b",
        "lease_id": "lease-b",
        "zero_idle_evidence": {
            "leased_at": "2026-08-18T14:50:01Z",
            "rule": "dispatch_independent_ready_work_while_other_resource_waits",
            "overlapped_external_waits": [{
                "task_id": "A", "worker_id": "cloud-a", "wait_started_at": "2026-08-18T14:50:00Z", "dispatch_id": "dispatch-a",
            }],
            "credential": "MUST_NOT_PROJECT",
        },
    })
    root = tmp_path / "state"
    _write(root / "agent_coordination" / "agent_manager_runtime.json", runtime)
    _write(root / "agent_coordination" / "manager_state.json", {"generated_at": "2026-08-18T14:50:01Z"})

    snapshot = ProductMissionRuntime(root, config_path=config_path).snapshot()

    task_a = next(task for task in snapshot["tasks"] if task["id"] == "A")
    task_b = next(task for task in snapshot["tasks"] if task["id"] == "B")
    assert task_a["external_wait_state"] == "WAITING_EXTERNAL"
    assert task_a["lease_id"] == "lease-a"
    assert task_a["fence_generation"] == 4
    assert task_a["dispatch_id"] == "dispatch-a"
    assert task_a["routing_decision"]["selected_worker"] == "cloud-a"
    assert task_a["routing_decision"]["candidates"][0]["observed"]["latency_ms"] == 45
    assert "secret_key" not in task_a["routing_decision"]
    assert "api_secret" not in task_a["routing_decision"]["candidates"][0]
    assert "private_token" not in task_a["routing_decision"]["candidates"][0]["observed"]
    assert task_b["zero_idle_evidence"]["overlapped_external_waits"][0]["task_id"] == "A"
    assert "credential" not in task_b["zero_idle_evidence"]
    assert snapshot["control_plane"]["external_waiting"] == [{
        "task_id": "A", "worker_id": "cloud-a", "wait_started_at": "2026-08-18T14:50:00Z", "dispatch_id": "dispatch-a",
    }]
    assert snapshot["control_plane"]["zero_idle_assignments"][0]["task_id"] == "B"
    cloud = next(worker for worker in snapshot["workers"] if worker["id"] == "cloud-a")
    assert cloud["routing_metrics"]["health_score"] == 0.97
    assert cloud["routing_metrics"]["latency_ms"] == 45
    assert snapshot["paper_only"] is True
    assert snapshot["live_trading_authority"] is False


def test_definition_only_does_not_fabricate_phase7_runtime_evidence(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write(config_path, _config())

    snapshot = ProductMissionRuntime(tmp_path / "state", config_path=config_path).snapshot()

    assert snapshot["source"] == "definition_only"
    assert snapshot["control_plane"]["runtime_present"] is False
    assert snapshot["control_plane"]["external_waiting"] == []
    assert snapshot["control_plane"]["zero_idle_assignments"] == []
    assert all(task["routing_decision"] is None for task in snapshot["tasks"])
    assert all(task["external_wait_state"] is None for task in snapshot["tasks"])
    assert all(task["zero_idle_evidence"] is None for task in snapshot["tasks"])
    assert all(worker["routing_metrics"] == {} for worker in snapshot["workers"])
