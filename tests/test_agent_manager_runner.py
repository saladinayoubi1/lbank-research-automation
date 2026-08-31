from __future__ import annotations

from agent_manager_runner import merge_definition, reconcile_blocked_successful_result


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


def test_successful_triage_result_rebinds_actual_producer_before_verification(monkeypatch):
    monkeypatch.setattr("agent_manager_runner.am.emit", lambda *args, **kwargs: None)
    config = {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4},
        "workers": [
            {
                "id": "architect-agent",
                "capabilities": ["architecture", "contract_review"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
                "max_concurrent_tasks": 1,
            },
            {
                "id": "qa-verifier-agent",
                "capabilities": ["contract_review", "root_cause_analysis", "diagnostics"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
                "max_concurrent_tasks": 2,
            },
        ],
        "tasks": [
            {
                "id": "P4-MGR-001",
                "status": "BLOCKED",
                "blocked_reason": "independent verifier unavailable",
                "producer": "architect-agent",
                "assigned_worker": "qa-verifier-agent",
                "priority": 100,
                "dependencies": [],
                "required_capabilities": ["architecture", "contract_review"],
                "preferred_resources": ["github-cloud"],
                "authority": 1,
                "result_evidence": {"tests": {"ok": True}},
            }
        ],
    }

    reconcile_blocked_successful_result(config)

    task = config["tasks"][0]
    assert task["producer"] == "qa-verifier-agent"
    assert task["status"] == "VERIFYING"
    assert task["verifier"] == "architect-agent"
    assert task["assigned_worker"] == "architect-agent"
