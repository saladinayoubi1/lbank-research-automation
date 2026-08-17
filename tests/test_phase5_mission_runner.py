from __future__ import annotations

import json

import agent_manager as am
import phase5_mission_contract as mc
import phase5_mission_runner as runner


def test_shadow_runner_writes_runtime_and_summary_without_touching_legacy_state(tmp_path, monkeypatch):
    mission = {
        "schema_version": mc.MISSION_SCHEMA,
        "mission_id": "shadow-test",
        "mission_revision": 1,
        "phase": 5,
        "policy": {"version": "p1", "max_parallel_tasks": 1},
        "workers": [
            {
                "id": "architect",
                "capabilities": ["architecture"],
                "resources": ["cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
            }
        ],
        "tasks": [
            {
                "id": "A",
                "title": "shadow",
                "phase": 5,
                "gate": 1,
                "status": "PENDING",
                "priority": 1,
                "dependencies": [],
                "required_capabilities": ["architecture"],
                "preferred_resources": ["cloud"],
                "authority": 1,
                "acceptance": ["leased"],
            }
        ],
    }
    mission_path = tmp_path / "mission.json"
    runtime_path = tmp_path / "runtime.json"
    summary_path = tmp_path / "summary.json"
    event_path = tmp_path / "events.jsonl"
    mission_path.write_text(json.dumps(mission), encoding="utf-8")
    monkeypatch.setattr(am, "EVENT_PATH", event_path)

    summary = runner.cycle_shadow(mission_path, runtime_path, summary_path)
    persisted = json.loads(runtime_path.read_text(encoding="utf-8"))

    assert persisted["phase5_runtime_schema"] == mc.RUNTIME_SCHEMA
    assert persisted["mission_id"] == "shadow-test"
    assert persisted["tasks"][0]["status"] == "LEASED"
    assert len(persisted["tasks"][0]["spec_digest"]) == 64
    assert summary["phase"] == 5
    assert summary_path.exists()


def test_shadow_runner_refuses_corrupt_existing_runtime(tmp_path, monkeypatch):
    mission_path = tmp_path / "mission.json"
    runtime_path = tmp_path / "runtime.json"
    summary_path = tmp_path / "summary.json"
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")

    mission_path.write_text(
        json.dumps(
            {
                "schema_version": mc.MISSION_SCHEMA,
                "mission_id": "shadow-test",
                "mission_revision": 1,
                "phase": 5,
                "policy": {"version": "p1", "max_parallel_tasks": 1},
                "workers": [],
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )
    runtime_path.write_text("{broken", encoding="utf-8")

    try:
        runner.cycle_shadow(mission_path, runtime_path, summary_path)
    except mc.RuntimeStateError:
        pass
    else:
        raise AssertionError("corrupt runtime must fail closed")

    assert not summary_path.exists()
