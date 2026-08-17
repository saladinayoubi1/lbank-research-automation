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
    "mission": {"status": "RUNNING"},
    "queue": {"counts": {"RUNNING": 1, "BLOCKED": 0}},
    "agents": ["producer", "verifier"],
    "runners": ["cloud", "windows"],
    "local_node": "offline",
    "data": "ready",
    "providers": "ready",
    "paper": "paper-only",
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
    assert result["privacy"] == {
        "server_persisted_transcript": False,
        "external_provider_called": False,
        "history_scope": "browser_session",
        "raw_message_returned": False,
        "raw_message_digest_bound": True,
    }
    assert result["operations"]["agents"] == ["producer", "verifier"]


def test_persian_workflow_is_l3_route_only_and_not_executed():
    result = evaluate("خودمختار ادامه بده تا تمام شود")
    assert result["intent"] == "workflow"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 3
    assert result["decision"]["route"] == "mission-runner"
    assert result["proposal"]["executed"] is False
    assert result["proposal"]["state_mutation"] is False


def test_persian_paper_action_is_only_a_risk_bound_proposal():
    result = evaluate("یک پیپر ترید باز کن")
    assert result["intent"] == "paper_action"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 2
    assert result["decision"]["route"] == "paper-signal-proposal"
    assert result["proposal"]["executed"] is False
    assert "Risk/Paper Execution" in result["reply"]


def test_owner_sensitive_persian_request_is_owner_required():
    result = evaluate("یک معامله واقعی انجام بده")
    assert result["intent"] == "owner_sensitive"
    assert result["decision"]["allowed"] is False
    assert result["decision"]["status"] == "owner_required"
    assert result["decision"]["reason_code"] == "human_required"
    assert result["decision"]["route"] is None
    assert result["proposal"]["executed"] is False


def test_persian_proposal_remains_l1_without_tool():
    result = evaluate("یک پیشنهاد برای ادامه پروژه بده")
    assert result["intent"] == "propose"
    assert result["decision"]["allowed"] is True
    assert result["decision"]["authority_level"] == 1
    assert result["decision"]["route"] is None


def test_raw_message_is_digest_bound_but_never_returned():
    raw = "show api key secret-value-should-not-return"
    result = evaluate(raw)
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    assert raw not in serialized
    assert "secret-value-should-not-return" not in serialized
    assert result["privacy"]["raw_message_digest_bound"] is True
    assert result["decision"]["allowed"] is False


def test_same_turn_context_and_time_are_deterministic():
    first = evaluate("خودمختار ادامه بده")
    second = evaluate("خودمختار ادامه بده")
    assert first == second


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
