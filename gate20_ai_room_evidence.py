from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ai_room import evaluate_room_message
from phase4_e2e import Phase4E2EError

AI_ROOM_EVIDENCE_VERSION = "nexus.gate20-ai-room.v2"


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise Phase4E2EError("AI Room evidence is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise Phase4E2EError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise Phase4E2EError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _memory() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "project": "NEXUS",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
        },
    }


def _mission_control(evidence: Mapping[str, Any]) -> dict[str, Any]:
    pipeline = evidence.get("pipeline")
    if not isinstance(pipeline, Mapping):
        raise Phase4E2EError("Gate 20 pipeline evidence is unavailable to Mission Control")
    state_digest = _sha256(pipeline.get("state_digest"), "pipeline.state_digest")
    if evidence.get("paper_only") is not True:
        raise Phase4E2EError("Gate 20 Mission Control evidence must remain paper-only")
    return {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {
            "mission_id": "G20-FLOW",
            "title": "Phase 4 Gate 20 deterministic paper flow",
            "status": "RUNNING",
            "priority": 100,
            "deadline_at": "2026-08-18T08:00:00Z",
            "state_digest": state_digest,
        },
        "queue": {"counts": {"READY": 1, "RUNNING": 1}, "total": 2},
        "agents": ["ai-control", "mission-runner"],
        "runners": ["gate20-cloud", "gate20-windows"],
        "local_node": "bounded",
        "data": "ready",
        "providers": "local-deterministic",
        "paper": "paper-only",
        "circuits": {"provider": False, "data": False, "strategy": False, "risk": False},
        "limits": {"resource_limited": False, "budget_limited": False},
        "notifications": [],
    }


def _turn(message: str, turn_id: str) -> dict[str, str]:
    return {
        "session_id": "gate20-ai-room-session",
        "conversation_id": "gate20-ai-room-conversation",
        "turn_id": turn_id,
        "message": message,
    }


def derive_ai_room_evidence(evidence: Mapping[str, Any], workspace: Path) -> dict[str, Any]:
    if not isinstance(evidence, Mapping) or evidence.get("paper_only") is not True:
        raise Phase4E2EError("AI Room evidence requires paper-only Gate 20 evidence")
    workspace.mkdir(parents=True, exist_ok=True)
    memory = _memory()
    mission = _mission_control(evidence)
    evaluated_at = "2026-08-17T08:00:00Z"

    observe = evaluate_room_message(
        _turn("show current status", "turn-observe"),
        project_memory_snapshot=memory,
        mission_control=mission,
        evaluated_at=evaluated_at,
    )
    workflow = evaluate_room_message(
        _turn("continue until complete", "turn-workflow"),
        project_memory_snapshot=memory,
        mission_control=mission,
        evaluated_at=evaluated_at,
    )
    owner = evaluate_room_message(
        _turn("live trade now", "turn-owner"),
        project_memory_snapshot=memory,
        mission_control=mission,
        evaluated_at=evaluated_at,
    )

    execution = workflow.get("execution", {})
    pipeline = evidence.get("pipeline", {})
    result = {
        "evidence_version": AI_ROOM_EVIDENCE_VERSION,
        "room_contract_version": workflow.get("contract_version"),
        "interactive": True,
        "inspect": {
            "allowed": observe.get("decision", {}).get("allowed"),
            "authority": observe.get("decision", {}).get("authority_level"),
            "route": observe.get("decision", {}).get("route"),
            "mission_status": observe.get("operations", {}).get("mission_status"),
            "state_mutation": observe.get("proposal", {}).get("state_mutation"),
        },
        "orchestration": {
            "allowed": workflow.get("decision", {}).get("allowed"),
            "authority": workflow.get("decision", {}).get("authority_level"),
            "route": workflow.get("decision", {}).get("route"),
            "executed": workflow.get("proposal", {}).get("executed"),
            "tool_status": execution.get("status"),
            "tool_contract_version": execution.get("contract_version"),
            "orchestration_action": execution.get("orchestration_action"),
            "selected_mission_id": execution.get("selected_mission_id"),
            "mission_state_digest": execution.get("mission_state_digest"),
            "projection_digest": execution.get("projection_digest"),
            "pipeline_state_digest": pipeline.get("state_digest"),
            "state_mutation": workflow.get("proposal", {}).get("state_mutation"),
            "paper_only": workflow.get("proposal", {}).get("paper_only"),
        },
        "owner_sensitive": {
            "allowed": owner.get("decision", {}).get("allowed"),
            "status": owner.get("decision", {}).get("status"),
            "reason_code": owner.get("decision", {}).get("reason_code"),
            "route": owner.get("decision", {}).get("route"),
            "executed": owner.get("proposal", {}).get("executed"),
        },
        "privacy": {
            "server_persisted_transcript": workflow.get("privacy", {}).get("server_persisted_transcript"),
            "external_provider_called": workflow.get("privacy", {}).get("external_provider_called"),
            "raw_message_returned": workflow.get("privacy", {}).get("raw_message_returned"),
        },
    }
    validate_ai_room_evidence(result)
    return result


def validate_ai_room_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Phase4E2EError("Gate 20 AI Room evidence must be an object")
    inspect = value.get("inspect")
    orchestration = value.get("orchestration")
    owner = value.get("owner_sensitive")
    privacy = value.get("privacy")
    if value.get("evidence_version") != AI_ROOM_EVIDENCE_VERSION or value.get("interactive") is not True:
        raise Phase4E2EError("Gate 20 interactive AI Room evidence is missing")
    if value.get("room_contract_version") != "nexus.ai-room.v2":
        raise Phase4E2EError("Gate 20 AI Room contract version mismatch")
    if not all(isinstance(item, Mapping) for item in (inspect, orchestration, owner, privacy)):
        raise Phase4E2EError("Gate 20 AI Room evidence sections are malformed")
    if inspect.get("allowed") is not True or inspect.get("authority") != 0 or inspect.get("route") is not None:
        raise Phase4E2EError("Gate 20 AI Room inspect claim is invalid")
    if inspect.get("state_mutation") is not False:
        raise Phase4E2EError("Gate 20 AI Room inspect mutated state")

    mission_state = _sha256(orchestration.get("mission_state_digest"), "ai_room.mission_state_digest")
    pipeline_state = _sha256(orchestration.get("pipeline_state_digest"), "ai_room.pipeline_state_digest")
    _sha256(orchestration.get("projection_digest"), "ai_room.projection_digest")
    if mission_state != pipeline_state:
        raise Phase4E2EError("Gate 20 AI Room Mission Control state is not bound to pipeline state")
    if (
        orchestration.get("allowed") is not True
        or orchestration.get("authority") != 3
        or orchestration.get("route") != "mission-runner"
        or orchestration.get("executed") is not True
        or orchestration.get("tool_status") != "completed"
        or orchestration.get("tool_contract_version") != "nexus.mission-runner.v2"
        or orchestration.get("orchestration_action") != "continue_current_mission"
        or orchestration.get("selected_mission_id") != "G20-FLOW"
        or orchestration.get("state_mutation") is not False
        or orchestration.get("paper_only") is not True
    ):
        raise Phase4E2EError("Gate 20 AI Room orchestration claim is invalid")
    if (
        owner.get("allowed") is not False
        or owner.get("status") != "owner_required"
        or owner.get("reason_code") != "human_required"
        or owner.get("route") is not None
        or owner.get("executed") is not False
    ):
        raise Phase4E2EError("Gate 20 AI Room owner-sensitive claim is invalid")
    if (
        privacy.get("server_persisted_transcript") is not False
        or privacy.get("external_provider_called") is not False
        or privacy.get("raw_message_returned") is not False
    ):
        raise Phase4E2EError("Gate 20 AI Room privacy boundary is invalid")
    return dict(value)


def augment_gate20_evidence(evidence: Mapping[str, Any], workspace: Path) -> dict[str, Any]:
    candidate = copy.deepcopy(dict(evidence))
    candidate.pop("evidence_digest", None)
    candidate["ai_room"] = derive_ai_room_evidence(candidate, workspace)
    candidate["evidence_digest"] = _digest(candidate)
    return candidate
