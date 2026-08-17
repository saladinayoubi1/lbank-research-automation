from __future__ import annotations

import json
from copy import deepcopy

import pytest

import phase5_mission_contract as mc


def mission_config():
    return {
        "schema_version": mc.MISSION_SCHEMA,
        "mission_id": "phase5-test",
        "mission_revision": 1,
        "phase": 5,
        "policy": {"version": "p1", "max_parallel_tasks": 2},
        "workers": [
            {
                "id": "dev",
                "capabilities": ["implementation"],
                "resources": ["cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
            }
        ],
        "tasks": [
            {
                "id": "A",
                "title": "first",
                "phase": 5,
                "gate": 1,
                "status": "PENDING",
                "priority": 10,
                "dependencies": [],
                "required_capabilities": ["implementation"],
                "preferred_resources": ["cloud"],
                "authority": 1,
                "acceptance": ["verified"],
            },
            {
                "id": "B",
                "title": "second",
                "phase": 5,
                "gate": 2,
                "status": "PENDING",
                "priority": 9,
                "dependencies": ["A"],
                "required_capabilities": ["implementation"],
                "preferred_resources": ["cloud"],
                "authority": 1,
                "acceptance": ["verified"],
            },
        ],
    }


def test_phase_metadata_does_not_change_authorization_spec_digest():
    first = mission_config()
    second = deepcopy(first)
    second["phase"] = 6
    second["tasks"][0]["phase"] = 6
    second["tasks"][0]["gate"] = 99
    second["tasks"][0]["title"] = "renamed"
    second["tasks"][0]["priority"] = 1
    second["tasks"][0]["preferred_resources"] = ["windows-local"]

    a = mc.validate_and_materialize(first)["tasks"][0]
    b = mc.validate_and_materialize(second)["tasks"][0]
    assert a["spec_digest"] == b["spec_digest"]


def test_authority_or_acceptance_change_changes_spec_digest():
    first = mission_config()
    second = deepcopy(first)
    second["tasks"][0]["authority"] = 2
    third = deepcopy(first)
    third["tasks"][0]["acceptance"] = ["stronger invariant"]

    base = mc.validate_and_materialize(first)["tasks"][0]["spec_digest"]
    assert mc.validate_and_materialize(second)["tasks"][0]["spec_digest"] != base
    assert mc.validate_and_materialize(third)["tasks"][0]["spec_digest"] != base


def test_policy_or_mission_revision_change_changes_spec_digest():
    first = mission_config()
    second = deepcopy(first)
    second["policy"]["version"] = "p2"
    third = deepcopy(first)
    third["mission_revision"] = 2

    base = mc.validate_and_materialize(first)["tasks"][0]["spec_digest"]
    assert mc.validate_and_materialize(second)["tasks"][0]["spec_digest"] != base
    assert mc.validate_and_materialize(third)["tasks"][0]["spec_digest"] != base


def test_dependency_cycle_fails_closed():
    cfg = mission_config()
    cfg["tasks"][0]["dependencies"] = ["B"]
    with pytest.raises(mc.MissionContractError, match="cycle"):
        mc.validate_and_materialize(cfg)


def test_unknown_and_self_dependency_fail_closed():
    cfg = mission_config()
    cfg["tasks"][0]["dependencies"] = ["MISSING"]
    with pytest.raises(mc.MissionContractError, match="unknown dependencies"):
        mc.validate_and_materialize(cfg)

    cfg = mission_config()
    cfg["tasks"][0]["dependencies"] = ["A"]
    with pytest.raises(mc.MissionContractError, match="self dependency"):
        mc.validate_and_materialize(cfg)


def test_materialized_agent_manager_config_binds_mission_identity():
    cfg = mc.to_agent_manager_config(mission_config())
    task = cfg["tasks"][0]
    assert cfg["phase5_runtime_schema"] == mc.RUNTIME_SCHEMA
    assert cfg["mission_id"] == "phase5-test"
    assert task["mission_id"] == "phase5-test"
    assert task["mission_revision"] == 1
    assert task["policy_version"] == "p1"
    assert len(task["spec_digest"]) == 64


def test_compatible_runtime_survives_phase_metadata_transition():
    template_config = mission_config()
    old_template = mc.to_agent_manager_config(template_config)
    runtime = deepcopy(old_template)
    runtime["tasks"][0].update({"status": "DONE", "attempt": 3, "verification_evidence": {"ok": True}})

    next_config = deepcopy(template_config)
    next_config["phase"] = 6
    next_config["tasks"][0]["phase"] = 6
    next_config["tasks"][0]["title"] = "new display title"
    next_template = mc.to_agent_manager_config(next_config)

    merged = mc.merge_compatible_runtime(next_template, runtime)
    assert merged["tasks"][0]["status"] == "DONE"
    assert merged["tasks"][0]["attempt"] == 3
    assert merged["tasks"][0]["verification_evidence"] == {"ok": True}
    assert merged["tasks"][0]["phase"] == 6


def test_spec_change_invalidates_prior_done_state():
    base = mission_config()
    runtime = mc.to_agent_manager_config(base)
    runtime["tasks"][0].update({"status": "DONE", "verification_evidence": {"old": True}})

    changed = deepcopy(base)
    changed["tasks"][0]["authority"] = 2
    merged = mc.merge_compatible_runtime(mc.to_agent_manager_config(changed), runtime)
    task = merged["tasks"][0]
    assert task["status"] == "PENDING"
    assert "verification_evidence" not in task


def test_removed_runtime_task_is_quarantined():
    base = mission_config()
    runtime = mc.to_agent_manager_config(base)
    runtime["tasks"][1]["status"] = "RUNNING"

    changed = deepcopy(base)
    changed["tasks"] = [changed["tasks"][0]]
    merged = mc.merge_compatible_runtime(mc.to_agent_manager_config(changed), runtime)
    historical = [task for task in merged["tasks"] if task["id"] == "B"][0]
    assert historical["status"] == "QUARANTINED"
    assert "removed" in historical["blocked_reason"]


def test_corrupt_runtime_never_silently_resets(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(mc.RuntimeStateError, match="corrupt"):
        mc.load_runtime_strict(path)


def test_wrong_runtime_schema_never_silently_resets(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps({"phase5_runtime_schema": "wrong", "tasks": []}), encoding="utf-8")
    with pytest.raises(mc.RuntimeStateError, match="unsupported"):
        mc.load_runtime_strict(path)
