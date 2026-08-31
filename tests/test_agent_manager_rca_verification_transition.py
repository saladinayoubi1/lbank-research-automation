from __future__ import annotations

from datetime import datetime, timezone

import agent_manager as am
import agent_manager_runner as runner


def _task(config, task_id):
    return next(task for task in config["tasks"] if task["id"] == task_id)


def test_successful_root_cause_analysis_requeues_original_task(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    config = am.load_config()
    runner.apply_provider_gates(config)
    task = _task(config, "P4-MGR-001")
    task.update(
        {
            "status": "VERIFYING",
            "producer": "architect-agent",
            "assigned_worker": "verification-agent-independent",
            "verifier": "verification-agent-independent",
            "triage_mode": "root_cause_first",
            "result_evidence": {"tests": "36 passed", "root_cause": "provider gate"},
            "result_received_at": "2026-08-31T03:00:00+00:00",
            "lease_id": "rca-lease",
            "dispatch_id": "rca-dispatch",
            "dispatch_transport": "github-cloud",
            "blocked_reason": None,
        }
    )

    assert runner.recover_completed_root_cause_analysis(config) == 1
    assert task["status"] == "READY"
    assert task["assigned_worker"] is None
    assert task["triage_mode"] is None
    assert task["result_evidence"] is None
    assert task["triage_evidence"]["evidence"]["tests"] == "36 passed"

    am.cycle(config, datetime(2026, 8, 31, 3, 1, tzinfo=timezone.utc))
    assert task["status"] == "LEASED"
    assert task["assigned_worker"] == "architect-agent"
    assert task["producer"] == "architect-agent"


def test_legacy_blocked_root_cause_state_is_recovered(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    config = am.load_config()
    runner.apply_provider_gates(config)
    task = _task(config, "P4-MGR-001")
    task.update(
        {
            "status": "BLOCKED",
            "producer": "architect-agent",
            "assigned_worker": "qa-verifier-agent",
            "triage_mode": "root_cause_first",
            "result_evidence": {"tests": "36 passed"},
            "result_received_at": "2026-08-31T02:53:42+00:00",
            "blocked_reason": "independent verifier unavailable",
        }
    )

    assert runner.recover_completed_root_cause_analysis(config) == 1
    assert task["status"] == "READY"
    assert task["blocked_reason"] is None
    assert task["triage_evidence"]["worker_id"] == "qa-verifier-agent"


def test_original_success_routes_to_distinct_architecture_verifier(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    config = am.load_config()
    runner.apply_provider_gates(config)
    task = _task(config, "P4-MGR-001")
    task.update(
        {
            "status": "RUNNING",
            "assigned_worker": "architect-agent",
            "producer": "architect-agent",
            "lease_id": "original-lease",
            "triage_mode": None,
        }
    )

    am.record_result(config, "P4-MGR-001", "architect-agent", "success", {"tests": "pass"})

    assert task["status"] == "VERIFYING"
    assert task["assigned_worker"] == "verification-agent-independent"
    assert task["verifier"] == "verification-agent-independent"
    assert task["verifier"] != task["producer"]


def test_closed_deepseek_gate_does_not_make_independent_verifier_a_deepseek_fallback(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    config = am.load_config()
    runner.apply_provider_gates(config)
    task = _task(config, "P4-DEEPSEEK-001")
    task["status"] = "READY"

    am.assign_ready_tasks(config, datetime(2026, 8, 31, 3, 2, tzinfo=timezone.utc))

    assert task["status"] == "READY"
    assert task.get("assigned_worker") is None
