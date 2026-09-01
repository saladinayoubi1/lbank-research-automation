from __future__ import annotations

from datetime import datetime, timezone

import agent_manager as am


NOW = datetime(2026, 9, 1, 4, 20, tzinfo=timezone.utc)


def config_with_specialized_failure() -> dict:
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {"max_parallel_tasks": 4, "blind_retry_forbidden": True},
        "workers": [
            {
                "id": "producer",
                "capabilities": ["implementation", "diagnostics"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": False,
            },
            {
                "id": "rca",
                "capabilities": ["diagnostics", "root_cause_analysis"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
            },
        ],
        "tasks": [
            {
                "id": "P4-SPECIALIZED",
                "status": "TRIAGE",
                "priority": 10,
                "dependencies": [],
                "required_capabilities": ["implementation"],
                "preferred_resources": ["github-cloud"],
                "authority": 1,
                "producer": "producer",
                "assigned_worker": "rca",
                "failure_class": "specialized_reasoning_provider_required",
                "failure_evidence": {
                    "failure_class": "specialized_reasoning_provider_required",
                    "reason": "specialized_reasoning_provider_required",
                },
                "attempt": 2,
                "lease_id": "stale-lease",
                "leased_at": "2026-09-01T04:10:00+00:00",
                "heartbeat_at": "2026-09-01T04:10:00+00:00",
                "lease_expires_at": "2026-09-01T04:15:00+00:00",
                "external_wait_state": am.WAITING_EXTERNAL,
                "external_wait_started_at": "2026-09-01T04:10:00+00:00",
            }
        ],
    }


def test_specialized_reasoning_failure_blocks_without_rca_redispatch():
    cfg = config_with_specialized_failure()
    task = cfg["tasks"][0]

    am.route_triage(cfg, NOW)

    assert task["status"] == "BLOCKED"
    assert task["assigned_worker"] is None
    assert task["blocked_reason"] == (
        "specialized reasoning provider required; no approved automatic provider available"
    )
    assert task["triage_mode"] == "fail_closed_specialized_reasoning_provider"
    assert task["lease_id"] is None
    assert task["leased_at"] is None
    assert task["heartbeat_at"] is None
    assert task["lease_expires_at"] is None
    assert task["external_wait_state"] is None
    assert task["external_wait_started_at"] is None
    assert task["attempt"] == 2
    assert task["failure_evidence"]["reason"] == "specialized_reasoning_provider_required"


def test_specialized_reasoning_block_remains_stable_across_manager_cycle():
    cfg = config_with_specialized_failure()
    task = cfg["tasks"][0]

    am.cycle(cfg, NOW)
    first_attempt = task["attempt"]
    first_reason = task["blocked_reason"]

    summary = am.cycle(cfg, NOW)

    assert task["status"] == "BLOCKED"
    assert task["assigned_worker"] is None
    assert task["attempt"] == first_attempt == 2
    assert task["blocked_reason"] == first_reason
    assert summary["counts"]["BLOCKED"] == 1
    assert summary["external_waiting"] == []
