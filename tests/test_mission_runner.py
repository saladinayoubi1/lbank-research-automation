from __future__ import annotations

import json

import pytest

from mission_runner import MissionRunnerError, orchestrate, run_mission_orchestration, validate_projection


def projection() -> dict:
    return {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {
            "mission_id": "phase4-final",
            "title": "Phase 4 final evidence",
            "status": "RUNNING",
            "priority": 100,
            "deadline_at": "2026-08-18T08:00:00Z",
            "state_digest": "a" * 64,
        },
        "queue": {"counts": {"READY": 1, "RUNNING": 1, "BLOCKED": 0}, "total": 2},
        "agents": ["producer", "verifier"],
        "runners": ["cloud", "windows"],
        "local_node": "offline",
        "data": "ready",
        "providers": "ready",
        "paper": "paper-only",
        "circuits": {"provider": False, "data": False, "strategy": False, "risk": False},
        "limits": {"resource_limited": False, "budget_limited": False},
        "notifications": [],
    }


def test_orchestration_is_deterministic_read_only_and_state_bound():
    payload = projection()
    before = json.loads(json.dumps(payload))
    first = orchestrate(payload)
    second = run_mission_orchestration(payload)
    assert first == second
    assert payload == before
    assert first["contract_version"] == "nexus.mission-runner.v2"
    assert first["executed"] is True
    assert first["state_mutation"] is False
    assert first["paper_only"] is True
    assert first["selected_mission_id"] == "phase4-final"
    assert first["parallel_mission_ids"] == ["phase4-final"]
    assert first["orchestration_action"] == "continue_current_mission"
    assert first["mission_state_digest"] == "a" * 64
    assert len(first["projection_digest"]) == 64
    assert first["ready_count"] == 1
    assert first["running_count"] == 1


def test_legacy_static_queue_is_rejected_instead_of_false_green():
    legacy = {
        "version": 2,
        "selectionPolicy": {"maxParallelMissions": 3},
        "missions": [],
    }
    with pytest.raises(MissionRunnerError, match="schema mismatch"):
        orchestrate(legacy)


def test_projection_contract_paper_boundary_and_state_digest_fail_closed():
    bad = projection()
    bad["contract_version"] = "legacy"
    with pytest.raises(MissionRunnerError, match="contract mismatch"):
        validate_projection(bad)

    bad = projection()
    bad["paper"] = "live"
    with pytest.raises(MissionRunnerError, match="paper-only"):
        orchestrate(bad)

    bad = projection()
    bad["mission"]["state_digest"] = "short"
    with pytest.raises(MissionRunnerError, match="SHA-256"):
        orchestrate(bad)


def test_queue_counts_and_bounds_fail_closed():
    bad = projection()
    bad["queue"]["total"] = 3
    with pytest.raises(MissionRunnerError, match="do not equal"):
        orchestrate(bad)

    bad = projection()
    bad["queue"]["total"] = 10_001
    bad["queue"]["counts"] = {"READY": 10_001}
    with pytest.raises(MissionRunnerError, match="exceeds bound"):
        orchestrate(bad)


def test_resource_circuit_and_terminal_states_produce_hold_or_noop_without_mutation():
    limited = projection()
    limited["limits"]["resource_limited"] = True
    result = orchestrate(limited)
    assert result["orchestration_action"] == "hold"
    assert result["reason_code"] == "resource_limit"
    assert result["state_mutation"] is False

    circuit = projection()
    circuit["circuits"]["risk"] = True
    result = orchestrate(circuit)
    assert result["orchestration_action"] == "hold"
    assert result["reason_code"] == "risk_circuit_open"

    done = projection()
    done["mission"]["status"] = "DONE"
    done["queue"] = {"counts": {"DONE": 2}, "total": 2}
    result = orchestrate(done)
    assert result["orchestration_action"] == "no_op"
    assert result["selected_mission_id"] is None
    assert result["parallel_mission_ids"] == []
