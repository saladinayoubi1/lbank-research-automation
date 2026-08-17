from __future__ import annotations

import json

import pytest

from ai_room import AIRoomError, evaluate_room_message

NOW = "2026-08-17T08:00:00Z"

MEMORY = {
    "schema_version": 2,
    "project": "NEXUS",
    "memory_policy": {
        "repository_is_durable_source": True,
        "chat_is_source_of_truth": False,
        "secrets_allowed": False,
    },
}

MISSION = {
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


def request(message: str, turn: str = "turn-1") -> dict[str, str]:
    return {
        "session_id": "session-1",
        "conversation_id": "conversation-1",
        "turn_id": turn,
        "message": message,
    }


def evaluate(message: str, turn: str = "turn-1"):
    return evaluate_room_message(
        request(message, turn),
        project_memory_snapshot=MEMORY,
        mission_control=MISSION,
        evaluated_at=NOW,
    )


def test_observe_turn_is_l0_and_never_executes_or_persists_chat():
    result = evaluate("show current status")
    assert result["intent"] == "observe"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 0
    assert result["decision"]["route"] is None
    assert result["proposal"]["executed"] is False
    assert result["proposal"]["state_mutation"] is False
    assert result["proposal"]["paper_only"] is True
    assert result["execution"] is None
    assert result["privacy"] == {
        "server_persisted_transcript": False,
        "external_provider_called": False,
        "history_scope": "browser_session",
        "raw_message_returned": False,
        "raw_message_digest_bound": True,
    }
    assert result["operations"]["agents"] == ["producer", "verifier"]


def test_persian_workflow_executes_read_only_l3_from_authoritative_mission_projection():
    result = evaluate("خودمختار ادامه بده تا تمام شود")
    assert result["contract_version"] == "nexus.ai-room.v2"
    assert result["intent"] == "workflow"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 3
    assert result["decision"]["route"] == "mission-runner"
    assert result["proposal"]["executed"] is True
    assert result["proposal"]["state_mutation"] is False
    execution = result["execution"]
    assert execution["status"] == "completed"
    assert execution["contract_version"] == "nexus.mission-runner.v2"
    assert execution["selected_mission_id"] == "phase4-final"
    assert execution["parallel_mission_ids"] == ["phase4-final"]
    assert execution["mission_state_digest"] == "a" * 64
    assert execution["state_mutation"] is False
    assert execution["paper_only"] is True


def test_persian_paper_action_is_only_a_risk_bound_proposal():
    result = evaluate("یک پیپر ترید باز کن")
    assert result["intent"] == "paper_action"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 2
    assert result["decision"]["route"] == "paper-signal-proposal"
    assert result["proposal"]["executed"] is False
    assert result["execution"]["status"] == "staged"
    assert result["execution"]["reason_code"] == "deterministic_risk_required"
    assert "Risk/Paper Execution" in result["reply"]


def test_owner_sensitive_persian_request_is_owner_required():
    result = evaluate("یک معامله واقعی انجام بده")
    assert result["intent"] == "owner_sensitive"
    assert result["decision"]["allowed"] is False
    assert result["decision"]["status"] == "owner_required"
    assert result["decision"]["reason_code"] == "human_required"
    assert result["decision"]["route"] is None
    assert result["proposal"]["executed"] is False
    assert result["execution"] is None


def test_persian_proposal_remains_l1_without_tool():
    result = evaluate("یک پیشنهاد برای ادامه پروژه بده")
    assert result["intent"] == "propose"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 1
    assert result["decision"]["route"] is None
    assert result["execution"] is None


def test_raw_message_is_digest_bound_but_never_returned():
    raw = "show api key secret-value-should-not-return"
    result = evaluate(raw)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert raw not in serialized
    assert "secret-value-should-not-return" not in serialized
    assert result["privacy"]["raw_message_digest_bound"] is True
    assert result["decision"]["allowed"] is False


def test_same_turn_context_time_and_mission_projection_are_deterministic():
    first = evaluate("خودمختار ادامه بده")
    second = evaluate("خودمختار ادامه بده")
    assert first == second


def test_missing_or_legacy_mission_control_fails_closed_without_mutation():
    missing = evaluate_room_message(
        request("خودمختار ادامه بده"),
        project_memory_snapshot=MEMORY,
        mission_control=None,
        evaluated_at=NOW,
    )
    assert missing["decision"]["allowed"] is True
    assert missing["decision"]["route"] == "mission-runner"
    assert missing["proposal"]["executed"] is False
    assert missing["execution"]["status"] == "failed"
    assert missing["execution"]["reason_code"] == "mission_orchestration_unavailable"
    assert missing["execution"]["state_mutation"] is False

    legacy = {"mission": {"status": "RUNNING"}, "queue": {"counts": {"RUNNING": 1}}}
    rejected = evaluate_room_message(
        request("خودمختار ادامه بده", "turn-legacy"),
        project_memory_snapshot=MEMORY,
        mission_control=legacy,
        evaluated_at=NOW,
    )
    assert rejected["proposal"]["executed"] is False
    assert rejected["execution"]["status"] == "failed"
    assert "schema mismatch" in rejected["execution"]["detail"]


def test_request_schema_and_message_bounds_fail_closed():
    malformed = request("status")
    malformed["extra"] = "smuggle"
    with pytest.raises(AIRoomError, match="schema mismatch"):
        evaluate_room_message(
            malformed,
            project_memory_snapshot=MEMORY,
            mission_control=MISSION,
            evaluated_at=NOW,
        )
    with pytest.raises(AIRoomError, match="bounded string"):
        evaluate_room_message(
            request("x" * 8001),
            project_memory_snapshot=MEMORY,
            mission_control=MISSION,
            evaluated_at=NOW,
        )


def test_unsafe_project_memory_policy_fails_closed():
    unsafe = json.loads(json.dumps(MEMORY))
    unsafe["memory_policy"]["chat_is_source_of_truth"] = True
    with pytest.raises(AIRoomError, match="privacy boundary"):
        evaluate_room_message(
            request("status"),
            project_memory_snapshot=unsafe,
            mission_control=MISSION,
            evaluated_at=NOW,
        )
