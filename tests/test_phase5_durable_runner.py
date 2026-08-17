from __future__ import annotations

import json
import sqlite3

import agent_manager as am
import phase5_durable_runner as runner


def _mission_payload():
    return {
        "schema_version": "nexus.phase5-mission.v1",
        "mission_id": "durable-runner-test",
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
                "title": "durable task",
                "phase": 5,
                "gate": 2,
                "status": "PENDING",
                "priority": 1,
                "dependencies": [],
                "required_capabilities": ["architecture"],
                "preferred_resources": ["cloud"],
                "authority": 1,
                "acceptance": ["durable"],
            }
        ],
    }


def test_durable_runner_survives_clean_restart_without_generation_churn(tmp_path, monkeypatch):
    mission_path = tmp_path / "mission.json"
    db_path = tmp_path / "state.sqlite3"
    summary_path = tmp_path / "summary.json"
    mission_path.write_text(json.dumps(_mission_payload()), encoding="utf-8")
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")

    first = runner.cycle_durable(mission_path, db_path, summary_path)
    second = runner.cycle_durable(mission_path, db_path, summary_path)

    assert first["state_generation"] == 0
    assert second["state_generation"] == 0
    assert first["state_sha256"] == second["state_sha256"]
    assert second["summary"]["counts"] == {"LEASED": 1}


def test_durable_runner_fails_closed_on_corrupt_tip_then_explicitly_recovers(tmp_path, monkeypatch):
    mission_path = tmp_path / "mission.json"
    db_path = tmp_path / "state.sqlite3"
    summary_path = tmp_path / "summary.json"
    mission_path.write_text(json.dumps(_mission_payload()), encoding="utf-8")
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")

    first = runner.cycle_durable(mission_path, db_path, summary_path)
    # Create a legitimate generation 1 before corrupting it.
    with sqlite3.connect(db_path) as conn:
        payload = conn.execute(
            "SELECT payload_json FROM snapshots WHERE mission_id=? AND generation=0",
            ("durable-runner-test",),
        ).fetchone()[0]
    changed = json.loads(payload)
    changed["tasks"][0]["attempt"] = 99

    import phase5_state_store as state

    store = state.SQLiteStateStore(db_path)
    second = store.compare_and_swap("durable-runner-test", 0, changed)
    assert second.generation == 1
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE snapshots SET payload_json=? WHERE mission_id=? AND generation=1",
            ('{"corrupt":true}', "durable-runner-test"),
        )
        conn.commit()

    try:
        runner.cycle_durable(mission_path, db_path, summary_path)
    except state.StateCorruption:
        pass
    else:
        raise AssertionError("normal durable cycle must not hide a corrupt current tip")

    recovered = runner.recover_durable(
        mission_path,
        db_path,
        summary_path,
        expected_tip_generation=1,
    )
    assert recovered["state_generation"] == 2
    assert recovered["transition_kind"] == "recovery"
    assert recovered["parent_generation"] == 0
    assert recovered["quarantined_generations"] == [1]
    assert recovered["state_sha256"] == first["state_sha256"]

    after = runner.cycle_durable(mission_path, db_path, summary_path)
    assert after["state_generation"] == 2
    assert after["summary"]["counts"] == {"LEASED": 1}


def test_definition_change_does_not_inherit_completed_runtime_evidence(tmp_path, monkeypatch):
    mission_path = tmp_path / "mission.json"
    db_path = tmp_path / "state.sqlite3"
    summary_path = tmp_path / "summary.json"
    mission = _mission_payload()
    mission_path.write_text(json.dumps(mission), encoding="utf-8")
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")

    runner.cycle_durable(mission_path, db_path, summary_path)

    import phase5_state_store as state

    store = state.SQLiteStateStore(db_path)
    current = store.load_current("durable-runner-test")
    completed = json.loads(json.dumps(current.payload))
    completed["tasks"][0]["status"] = "DONE"
    completed["tasks"][0]["verification_evidence"] = {"old": True}
    store.compare_and_swap("durable-runner-test", current.generation, completed)

    mission["tasks"][0]["authority"] = 2
    mission["mission_revision"] = 2
    mission_path.write_text(json.dumps(mission), encoding="utf-8")
    result = runner.cycle_durable(mission_path, db_path, summary_path)

    assert result["summary"]["counts"].get("DONE", 0) == 0
    assert result["summary"]["counts"] == {"LEASED": 1}
