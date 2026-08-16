from __future__ import annotations

from agent_manager_runner import merge_definition


def test_runtime_state_survives_non_security_definition_refresh():
    template = {
        "schema_version": 1,
        "phase": 4,
        "policy": {},
        "workers": [],
        "tasks": [{
            "id": "A", "title": "new title", "phase": 4, "gate": 2,
            "priority": 10, "dependencies": [], "required_capabilities": [],
            "preferred_resources": [], "authority": 1, "acceptance": ["same"],
            "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1,
        "phase": 4,
        "tasks": [{
            "id": "A", "title": "old title", "phase": 4, "gate": 2,
            "priority": 9, "dependencies": [], "required_capabilities": [],
            "preferred_resources": ["old"], "authority": 1, "acceptance": ["same"],
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


def test_authority_escalation_invalidates_persisted_done_state():
    template = {
        "schema_version": 1, "phase": 4, "policy": {}, "workers": [],
        "tasks": [{
            "id": "L4", "phase": 4, "gate": 18, "dependencies": [],
            "required_capabilities": [], "authority": 4,
            "acceptance": ["owner only"], "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1, "phase": 4,
        "tasks": [{
            "id": "L4", "phase": 4, "gate": 18, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["owner only"], "status": "DONE",
            "producer": "dev", "verification_evidence": {"old": True}
        }],
    }
    task = merge_definition(template, runtime)["tasks"][0]
    assert task["status"] == "PENDING"
    assert "producer" not in task
    assert "verification_evidence" not in task


def test_acceptance_change_requires_fresh_execution_and_verification():
    template = {
        "schema_version": 1, "phase": 4, "policy": {}, "workers": [],
        "tasks": [{
            "id": "A", "phase": 4, "gate": 2, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["new invariant"], "status": "PENDING"
        }],
    }
    runtime = {
        "schema_version": 1, "phase": 4,
        "tasks": [{
            "id": "A", "phase": 4, "gate": 2, "dependencies": [],
            "required_capabilities": [], "authority": 1,
            "acceptance": ["old invariant"], "status": "DONE",
            "verification_evidence": {"old": True}
        }],
    }
    task = merge_definition(template, runtime)["tasks"][0]
    assert task["status"] == "PENDING"
    assert "verification_evidence" not in task


def test_removed_runtime_task_is_quarantined_not_silently_dropped():
    template = {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []}
    runtime = {"schema_version": 1, "phase": 3, "tasks": [{"id": "OLD", "status": "RUNNING"}]}
    merged = merge_definition(template, runtime)
    assert merged["tasks"][0]["id"] == "OLD"
    assert merged["tasks"][0]["status"] == "QUARANTINED"
