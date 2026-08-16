from __future__ import annotations

from agent_manager_runner import merge_definition


def test_runtime_state_survives_definition_refresh_without_authority_drift():
    template = {
        "schema_version": 1,
        "phase": 4,
        "policy": {},
        "workers": [],
        "tasks": [{
            "id": "A", "title": "new title", "phase": 4, "gate": 2,
            "priority": 10, "dependencies": [], "required_capabilities": [],
            "preferred_resources": [], "authority": 1, "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1,
        "phase": 4,
        "tasks": [{
            "id": "A", "title": "old title", "authority": 3, "dependencies": ["X"],
            "status": "VERIFYING", "producer": "dev", "verifier": "qa", "attempt": 2
        }],
    }
    merged = merge_definition(template, runtime)
    task = merged["tasks"][0]
    assert task["status"] == "VERIFYING"
    assert task["producer"] == "dev"
    assert task["attempt"] == 2
    assert task["title"] == "new title"
    assert task["authority"] == 1
    assert task["dependencies"] == []


def test_removed_runtime_task_is_quarantined_not_silently_dropped():
    template = {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []}
    runtime = {"schema_version": 1, "phase": 3, "tasks": [{"id": "OLD", "status": "RUNNING"}]}
    merged = merge_definition(template, runtime)
    assert merged["tasks"][0]["id"] == "OLD"
    assert merged["tasks"][0]["status"] == "QUARANTINED"
