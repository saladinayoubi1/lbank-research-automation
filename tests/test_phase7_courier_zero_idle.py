from __future__ import annotations

from datetime import timedelta

import agent_manager as am
import offline_agent_courier as courier


KEY = "phase7-proof-key-" + "x" * 40


def config() -> dict:
    now = am.utcnow()
    return {
        "schema_version": 1,
        "phase": 7,
        "policy": {
            "max_parallel_tasks": 3,
            "offline_courier_workers": ["windows-runner"],
            "offline_courier_lease_minutes": 240,
        },
        "workers": [
            {
                "id": "windows-runner",
                "capabilities": ["data_validation"],
                "resources": ["windows-local"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
                "max_concurrent_tasks": 1,
            },
            {
                "id": "cloud-worker",
                "capabilities": ["integration_tests"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
                "max_concurrent_tasks": 1,
            },
        ],
        "tasks": [
            {
                "id": "P7-LAPTOP-CANONICAL",
                "title": "offline laptop proof",
                "phase": 7,
                "gate": 0,
                "status": "LEASED",
                "priority": 100,
                "dependencies": [],
                "required_capabilities": ["data_validation"],
                "preferred_resources": ["windows-local"],
                "authority": 1,
                "acceptance": ["offline proof"],
                "assigned_worker": "windows-runner",
                "producer": "windows-runner",
                "lease_id": "phase7-laptop-lease",
                "leased_at": am.iso(now),
                "heartbeat_at": am.iso(now),
                "lease_expires_at": am.iso(now + timedelta(minutes=5)),
                "attempt": 1,
            },
            {
                "id": "P7-CLOUD-VERIFY",
                "title": "independent cloud work",
                "phase": 7,
                "gate": 0,
                "status": "READY",
                "priority": 90,
                "dependencies": [],
                "required_capabilities": ["integration_tests"],
                "preferred_resources": ["github-cloud"],
                "authority": 1,
                "acceptance": ["cloud proof"],
            },
        ],
    }


def test_offline_export_marks_real_external_wait_then_ready_cloud_work_records_overlap(monkeypatch, tmp_path):
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    cfg = config()
    runtime = tmp_path / "runtime.json"
    summary = tmp_path / "summary.json"
    courier.export_task(
        cfg,
        "P7-LAPTOP-CANONICAL",
        tmp_path / "dispatch.json",
        runtime_path=runtime,
        summary_path=summary,
    )

    laptop = cfg["tasks"][0]
    assert laptop["external_wait_state"] == am.WAITING_EXTERNAL
    assert laptop["waiting_from_status"] == "LEASED"
    assert laptop["external_wait_timeline"][-1]["mode"] == "offline-courier"
    assert laptop["heartbeat_at"] is None

    am.assign_ready_tasks(cfg, am.utcnow())
    cloud = cfg["tasks"][1]
    assert cloud["status"] == "LEASED"
    assert cloud["assigned_worker"] == "cloud-worker"
    overlap = cloud["zero_idle_evidence"]["overlapped_external_waits"]
    assert [row["task_id"] for row in overlap] == ["P7-LAPTOP-CANONICAL"]
    assert overlap[0]["dispatch_id"] == laptop["dispatch_id"]


def test_idempotent_reexport_does_not_duplicate_wait_timeline(monkeypatch, tmp_path):
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    cfg = config()
    runtime = tmp_path / "runtime.json"
    summary = tmp_path / "summary.json"
    output = tmp_path / "dispatch.json"

    first = courier.export_task(cfg, "P7-LAPTOP-CANONICAL", output, runtime_path=runtime, summary_path=summary)
    second = courier.export_task(cfg, "P7-LAPTOP-CANONICAL", output, runtime_path=runtime, summary_path=summary)

    assert first["payload_sha256"] == second["payload_sha256"]
    assert len(cfg["tasks"][0]["external_wait_timeline"]) == 1
