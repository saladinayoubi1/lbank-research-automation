from __future__ import annotations

from datetime import datetime, timezone

import agent_manager as am
import agent_manager_runner as runner


def _deepseek_worker(config):
    return next(worker for worker in config["workers"] if worker["id"] == "deepseek-bounded")


def test_closed_paid_routing_gate_keeps_deepseek_out_of_triage(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    config = am.load_config()
    runner.apply_provider_gates(config)

    assert _deepseek_worker(config)["enabled"] is False

    task = next(task for task in config["tasks"] if task["id"] == "P4-MGR-001")
    task.update(
        {
            "status": "TRIAGE",
            "producer": "architect-agent",
            "failure_class": "provider_budget_gate_closed",
        }
    )
    am.route_triage(config, datetime(2026, 8, 31, 2, 45, tzinfo=timezone.utc))

    assert task["status"] == "RUNNING"
    assert task["assigned_worker"] != "deepseek-bounded"
    selected = next(worker for worker in config["workers"] if worker["id"] == task["assigned_worker"])
    assert "github-cloud" in selected["resources"]


def test_explicit_paid_routing_gate_preserves_deepseek_availability(monkeypatch):
    monkeypatch.setenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", "1")
    config = am.load_config()
    runner.apply_provider_gates(config)

    assert _deepseek_worker(config)["enabled"] is True
