from __future__ import annotations

from agent_manager_runner import (
    SPECIALIZED_REASONING_BLOCK_REASON,
    block_unroutable_specialized_reasoning,
    merge_definition,
    recover_completed_root_cause_analysis,
)


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


def test_specialized_reasoning_failure_is_blocked_instead_of_blind_redispatch():
    config = {
        "tasks": [{
            "id": "P4-UI-001",
            "status": "READY",
            "failure_class": "specialized_reasoning_provider_required",
            "assigned_worker": None,
            "dispatch_id": "stale-dispatch",
            "dispatch_transport": "github-cloud",
            "external_wait_state": "WAITING_EXTERNAL",
        }]
    }

    blocked = block_unroutable_specialized_reasoning(config)
    task = config["tasks"][0]

    assert blocked == 1
    assert task["status"] == "BLOCKED"
    assert task["blocked_reason"] == SPECIALIZED_REASONING_BLOCK_REASON
    assert task["assigned_worker"] is None
    assert task["dispatch_id"] is None
    assert task["dispatch_transport"] is None
    assert task["external_wait_state"] is None


def test_completed_rca_does_not_requeue_specialized_failure_to_deterministic_worker():
    config = {
        "tasks": [{
            "id": "P4-UI-001",
            "status": "VERIFYING",
            "failure_class": "specialized_reasoning_provider_required",
            "triage_mode": "root_cause_first",
            "assigned_worker": "qa-verifier-agent",
            "producer": "architect-agent",
            "result_evidence": {"root_cause": "reasoning provider required"},
            "result_received_at": "2026-09-01T04:00:00+00:00",
            "dispatch_id": "rca-dispatch",
            "dispatch_transport": "github-cloud",
        }]
    }

    assert recover_completed_root_cause_analysis(config) == 1
    assert config["tasks"][0]["status"] == "READY"
    assert block_unroutable_specialized_reasoning(config) == 1
    assert config["tasks"][0]["status"] == "BLOCKED"
    assert config["tasks"][0]["triage_evidence"]["evidence"]["root_cause"] == "reasoning provider required"


def test_bounded_event_recovery_workload_is_not_blocked_by_stale_specialized_failure():
    config = {
        "tasks": [{
            "id": "P4-EVENT-001",
            "status": "READY",
            "failure_class": "specialized_reasoning_provider_required",
            "assigned_worker": None,
        }]
    }

    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "READY"


def test_specialized_reasoning_block_is_idempotent():
    config = {
        "tasks": [{
            "id": "P4-UI-001",
            "status": "BLOCKED",
            "failure_class": "specialized_reasoning_provider_required",
            "blocked_reason": SPECIALIZED_REASONING_BLOCK_REASON,
        }]
    }

    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "BLOCKED"


def test_specialized_reasoning_guard_does_not_change_transient_triage():
    config = {
        "tasks": [{
            "id": "A",
            "status": "TRIAGE",
            "failure_class": "timed_out",
            "assigned_worker": None,
        }]
    }

    assert block_unroutable_specialized_reasoning(config) == 0
    assert config["tasks"][0]["status"] == "TRIAGE"
