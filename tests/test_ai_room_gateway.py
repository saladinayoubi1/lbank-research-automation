from __future__ import annotations

import json
from http import HTTPStatus
from pathlib import Path

from web_ui_server import dispatch_ai_post, load_runtime_asset


def write_memory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": 2,
        "project": "NEXUS",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
        },
    }), encoding="utf-8")


def mission_projection() -> dict:
    return {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {
            "mission_id": "phase4-gateway",
            "title": "Phase 4 gateway mission",
            "status": "RUNNING",
            "priority": 100,
            "deadline_at": "2026-08-18T08:00:00Z",
            "state_digest": "b" * 64,
        },
        "queue": {"counts": {"READY": 1, "RUNNING": 1}, "total": 2},
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


def write_mission_report(data_root: Path) -> None:
    path = data_root.parent / "mission_control" / "_mission_control.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mission_projection()), encoding="utf-8")


def request(message: str = "show status") -> dict[str, str]:
    return {
        "session_id": "session-1",
        "conversation_id": "conversation-1",
        "turn_id": "turn-1",
        "message": message,
    }


def test_only_exact_ai_room_post_route_is_accepted(tmp_path: Path):
    memory = tmp_path / "STATE.json"
    write_memory(memory)
    data = tmp_path / "data" / "market"

    allowed = dispatch_ai_post(
        "/api/ai-room/message",
        request(),
        data_root=data,
        project_memory_path=memory,
        evaluated_at="2026-08-17T08:00:00Z",
    )
    assert allowed.status == HTTPStatus.OK
    assert allowed.payload["contract_version"] == "nexus.dashboard.read.v1"
    assert allowed.payload["ai_room"]["contract_version"] == "nexus.ai-room.v2"
    assert allowed.payload["ai_room"]["proposal"]["executed"] is False

    denied = dispatch_ai_post(
        "/api/mission-control",
        request(),
        data_root=data,
        project_memory_path=memory,
    )
    assert denied.status == HTTPStatus.METHOD_NOT_ALLOWED
    assert denied.payload["allowed"] == ["GET", "HEAD"]


def test_browser_workflow_turn_executes_only_read_only_authoritative_mission_runner(tmp_path: Path):
    memory = tmp_path / "STATE.json"
    write_memory(memory)
    data = tmp_path / "data" / "market"
    write_mission_report(data)
    response = dispatch_ai_post(
        "/api/ai-room/message",
        request("خودمختار ادامه بده تا تمام شود"),
        data_root=data,
        project_memory_path=memory,
        evaluated_at="2026-08-17T08:00:00Z",
    )
    assert response.status == HTTPStatus.OK
    room = response.payload["ai_room"]
    assert room["decision"]["route"] == "mission-runner"
    assert room["decision"]["authority_level"] == 3
    assert room["proposal"] == {
        "action": "run_bounded_mission_orchestration",
        "route": "mission-runner",
        "executed": True,
        "state_mutation": False,
        "paper_only": True,
    }
    assert room["execution"]["contract_version"] == "nexus.mission-runner.v2"
    assert room["execution"]["selected_mission_id"] == "phase4-gateway"
    assert room["execution"]["mission_state_digest"] == "b" * 64
    assert room["execution"]["executed"] is True
    assert room["execution"]["state_mutation"] is False


def test_browser_workflow_without_mission_control_report_fails_closed(tmp_path: Path):
    memory = tmp_path / "STATE.json"
    write_memory(memory)
    response = dispatch_ai_post(
        "/api/ai-room/message",
        request("خودمختار ادامه بده تا تمام شود"),
        data_root=tmp_path / "data" / "market",
        project_memory_path=memory,
        evaluated_at="2026-08-17T08:00:00Z",
    )
    assert response.status == HTTPStatus.OK
    room = response.payload["ai_room"]
    assert room["decision"]["route"] == "mission-runner"
    assert room["proposal"]["executed"] is False
    assert room["execution"]["status"] == "failed"
    assert room["execution"]["reason_code"] == "mission_orchestration_unavailable"


def test_ai_room_post_rejects_query_and_unknown_request_fields(tmp_path: Path):
    memory = tmp_path / "STATE.json"
    write_memory(memory)
    data = tmp_path / "data" / "market"
    query = dispatch_ai_post(
        "/api/ai-room/message?authority=4",
        request(),
        data_root=data,
        project_memory_path=memory,
    )
    assert query.status == HTTPStatus.BAD_REQUEST
    assert query.payload["error"] == "invalid_query"

    smuggled = request()
    smuggled["requested_authority"] = "4"
    response = dispatch_ai_post(
        "/api/ai-room/message",
        smuggled,
        data_root=data,
        project_memory_path=memory,
        evaluated_at="2026-08-17T08:00:00Z",
    )
    assert response.status == HTTPStatus.BAD_REQUEST
    assert response.payload["error"] == "invalid_ai_room_request"


def test_missing_project_memory_blocks_ai_room(tmp_path: Path):
    response = dispatch_ai_post(
        "/api/ai-room/message",
        request(),
        data_root=tmp_path / "data" / "market",
        project_memory_path=tmp_path / "missing.json",
    )
    assert response.status == HTTPStatus.SERVICE_UNAVAILABLE
    assert response.payload["error"] == "ai_context_unavailable"


def test_runtime_bundle_contains_interactive_client_and_styles(tmp_path: Path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "app.js").write_text("const baseApp = true;", encoding="utf-8")
    (ui / "ai_room.js").write_text("/api/ai-room/message sessionStorage", encoding="utf-8")
    (ui / "phase4.css").write_text(".view{}", encoding="utf-8")
    (ui / "ai_room.css").write_text(".ai-room-layout{}", encoding="utf-8")

    script = load_runtime_asset("/ui/app.js", ui)
    style = load_runtime_asset("/ui/phase4.css", ui)
    assert script is not None and b"baseApp" in script.body
    assert b"/api/ai-room/message" in script.body and b"sessionStorage" in script.body
    assert style is not None and b".ai-room-layout" in style.body


def test_real_ai_room_client_declares_bounded_execution_and_no_trading_mutation():
    script = Path("web_ui/ai_room.js").read_text(encoding="utf-8")
    assert "/api/ai-room/message" in script
    assert "sessionStorage" in script
    assert "Read-only mission orchestration" in script
    assert "State mutation" in script
    assert "external_provider_called" in script
    assert "paper-signal-proposal" not in script
