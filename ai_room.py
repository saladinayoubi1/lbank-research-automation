from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from ai_control_plane import AIControlPlaneError, classify_intent, evaluate_ai_action

AI_ROOM_CONTRACT_VERSION = "nexus.ai-room.v1"
MAX_PROJECT_MEMORY_BYTES = 1_000_000
REQUEST_KEYS = {"session_id", "conversation_id", "turn_id", "message"}

TOOL_REGISTRY = {
    "paper-signal-proposal": {
        "tool_id": "paper-signal-proposal",
        "enabled": True,
        "max_authority": 2,
        "reversible": True,
        "allowed_intents": ["paper_action"],
        "max_timeout_seconds": 15,
    },
    "mission-runner": {
        "tool_id": "mission-runner",
        "enabled": True,
        "max_authority": 3,
        "reversible": True,
        "allowed_intents": ["workflow"],
        "max_timeout_seconds": 30,
    },
}

POLICY = {
    "policy_version": "phase4-ai-room-policy-v1",
    "max_retry_count": 2,
    "max_timeout_seconds": 30,
    "max_delegation_depth": 2,
    "autonomous_authority_levels": [0, 1, 2, 3],
    "human_required_actions": ["production_deploy", "billing_change", "sign_release"],
}

MODEL = {
    "provider_id": "nexus-local",
    "model_id": "deterministic-ops-room",
    "model_version": "v1",
}

_PERSIAN_OWNER_TERMS = (
    "پروداکشن", "محیط اصلی", "معامله واقعی", "ترید واقعی", "برداشت", "صورتحساب",
    "کلید خصوصی", "کلید api", "کلید ای پی آی", "امضا کن",
)
_PERSIAN_WORKFLOW_TERMS = (
    "خودمختار", "خودکار", "گردش کار", "واگذار", "ادامه بده", "تا تمام", "تا تموم",
)
_PERSIAN_PAPER_TERMS = (
    "معامله کاغذی", "پیپر ترید", "پیپر", "پوزیشن باز", "پوزیشن ببند", "کیل سوئیچ",
)
_PERSIAN_PROPOSAL_TERMS = ("پیشنهاد", "توصیه", "طرح", "برنامه بده", "نقشه بده")
_CLASSIFIER_SENTINELS = {
    "owner_sensitive": "production",
    "workflow": "workflow",
    "paper_action": "paper trade",
    "propose": "propose",
    "observe": "observe status",
}


class AIRoomError(ValueError):
    """Raised when the interactive AI Room request/context is unsafe or malformed."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AIRoomError("value is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _bounded_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise AIRoomError(f"{field} must be a non-empty bounded string")
    return value


def _utc(value: str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if not isinstance(value, str):
        raise AIRoomError("evaluated_at must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AIRoomError("evaluated_at must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise AIRoomError("evaluated_at must be UTC")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _classify_room_intent(message: str) -> tuple[str, str]:
    """Add deterministic Persian coverage while preserving Gate 10's classifier authority."""
    base = classify_intent(message)
    if base != "observe":
        return base, message
    text = message.casefold()
    for intent, terms in (
        ("owner_sensitive", _PERSIAN_OWNER_TERMS),
        ("workflow", _PERSIAN_WORKFLOW_TERMS),
        ("paper_action", _PERSIAN_PAPER_TERMS),
        ("propose", _PERSIAN_PROPOSAL_TERMS),
    ):
        if any(term in text for term in terms):
            # Gate 10 re-classifies current_message independently. Feed it only a
            # canonical intent sentinel; the original message remains bound by a
            # SHA-256 digest in working context and is never persisted server-side.
            return intent, _CLASSIFIER_SENTINELS[intent]
    return "observe", message


def load_project_memory_snapshot(path: Path) -> dict[str, Any]:
    """Load bounded repository-authoritative Project Memory; raw chat is never read/written here."""
    try:
        if path.stat().st_size > MAX_PROJECT_MEMORY_BYTES:
            raise AIRoomError("Project Memory exceeds bounded size")
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AIRoomError("Project Memory is unavailable") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AIRoomError("Project Memory is invalid") from exc
    if not isinstance(payload, dict):
        raise AIRoomError("Project Memory root must be an object")
    policy = payload.get("memory_policy")
    if not isinstance(policy, Mapping):
        raise AIRoomError("Project Memory policy is missing")
    if policy.get("repository_is_durable_source") is not True:
        raise AIRoomError("Project Memory is not repository-authoritative")
    if policy.get("chat_is_source_of_truth") is not False or policy.get("secrets_allowed") is not False:
        raise AIRoomError("Project Memory privacy boundary is unsafe")
    return payload


def _mission_projection(mission_control: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(mission_control, Mapping):
        return {
            "availability": "unavailable",
            "mission_status": "unknown",
            "agents": [],
            "runners": [],
            "paper": "unknown",
        }
    mission = mission_control.get("mission")
    queue = mission_control.get("queue")
    counts = queue.get("counts", {}) if isinstance(queue, Mapping) else {}
    safe_counts = {
        key: int(value)
        for key, value in counts.items()
        if isinstance(key, str) and isinstance(value, int) and not isinstance(value, bool) and value >= 0
    }
    agents = mission_control.get("agents")
    runners = mission_control.get("runners")
    return {
        "availability": "available",
        "mission_status": mission.get("status", "unknown") if isinstance(mission, Mapping) else "unknown",
        "queue_counts": safe_counts,
        "agents": [str(item)[:160] for item in agents[:32]] if isinstance(agents, list) else [],
        "runners": [str(item)[:160] for item in runners[:32]] if isinstance(runners, list) else [],
        "local_node": str(mission_control.get("local_node", "unknown"))[:160],
        "data": str(mission_control.get("data", "unknown"))[:160],
        "providers": str(mission_control.get("providers", "unknown"))[:160],
        "paper": str(mission_control.get("paper", "unknown"))[:160],
    }


def _model_output(intent: str) -> dict[str, Any]:
    if intent == "observe":
        return {
            "intent": intent, "action": "inspect_status", "tool": None, "parameters": {},
            "requested_authority": 0, "retry_count": 0, "timeout_seconds": 10,
            "delegation_depth": 0, "cancel_requested": False,
        }
    if intent == "propose":
        return {
            "intent": intent, "action": "propose_plan", "tool": None, "parameters": {},
            "requested_authority": 1, "retry_count": 0, "timeout_seconds": 10,
            "delegation_depth": 0, "cancel_requested": False,
        }
    if intent == "paper_action":
        return {
            "intent": intent, "action": "stage_paper_signal_proposal", "tool": "paper-signal-proposal",
            "parameters": {"mode": "paper_only", "state_mutation": False},
            "requested_authority": 2, "retry_count": 0, "timeout_seconds": 15,
            "delegation_depth": 0, "cancel_requested": False,
        }
    if intent == "workflow":
        return {
            "intent": intent, "action": "stage_bounded_workflow", "tool": "mission-runner",
            "parameters": {"mode": "paper_research_only", "state_mutation": False},
            "requested_authority": 3, "retry_count": 0, "timeout_seconds": 30,
            "delegation_depth": 1, "cancel_requested": False,
        }
    return {
        "intent": "owner_sensitive", "action": "owner_sensitive_request", "tool": None,
        "parameters": {}, "requested_authority": 4, "retry_count": 0, "timeout_seconds": 10,
        "delegation_depth": 0, "cancel_requested": False,
    }


def _reply(intent: str, decision: Mapping[str, Any], operations: Mapping[str, Any]) -> str:
    status = str(decision.get("status", "blocked"))
    reason = str(decision.get("reason_code", "unknown"))
    if status == "owner_required":
        return f"Owner approval is required. The request was not executed ({reason})."
    if not decision.get("allowed"):
        return f"The request was blocked by the AI authority gate ({reason}). No state was changed."
    if intent == "workflow":
        return "The bounded workflow route is policy-valid. It is staged only; this chat endpoint did not execute or mutate project state."
    if intent == "paper_action":
        return "The paper-action proposal passed the AI gate. It is staged only and still requires the deterministic Risk/Paper Execution path before any simulated state change."
    if intent == "propose":
        return "The request is accepted as a proposal. No tool was invoked and no project state was changed."
    mission = operations.get("mission_status", "unknown")
    paper = operations.get("paper", "unknown")
    return f"Mission Control status: {mission}; paper state: {paper}. This was an observe-only request and changed no state."


def evaluate_room_message(
    request: Mapping[str, Any],
    *,
    project_memory_snapshot: Mapping[str, Any],
    mission_control: Mapping[str, Any] | None = None,
    evaluated_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate one browser chat turn without executing tools or persisting the raw transcript."""
    if not isinstance(request, Mapping) or set(request) != REQUEST_KEYS:
        raise AIRoomError("AI Room request schema mismatch")
    session_id = _bounded_identifier(request["session_id"], "session_id")
    conversation_id = _bounded_identifier(request["conversation_id"], "conversation_id")
    turn_id = _bounded_identifier(request["turn_id"], "turn_id")
    message = request["message"]
    if not isinstance(message, str) or not message.strip() or len(message) > 8_000:
        raise AIRoomError("message must be a non-empty bounded string")
    if not isinstance(project_memory_snapshot, Mapping):
        raise AIRoomError("Project Memory snapshot is malformed")
    memory_policy = project_memory_snapshot.get("memory_policy")
    if not isinstance(memory_policy, Mapping):
        raise AIRoomError("Project Memory policy is missing")
    if memory_policy.get("repository_is_durable_source") is not True:
        raise AIRoomError("Project Memory is not repository-authoritative")
    if memory_policy.get("chat_is_source_of_truth") is not False or memory_policy.get("secrets_allowed") is not False:
        raise AIRoomError("Project Memory privacy boundary is unsafe")

    now = _utc(evaluated_at)
    now_text = _iso(now)
    operations = _mission_projection(mission_control)
    intent, classifier_message = _classify_room_intent(message)
    proposal = _model_output(intent)
    working_context = {
        "operations": operations,
        "raw_message_digest": _text_digest(message),
    }
    context = {
        "context_id": f"ai-room-context-{_text_digest(turn_id)[:24]}",
        "conversation_id": conversation_id,
        "provenance_id": "nexus-ai-room-runtime",
        "generated_at": now_text,
        "expires_at": _iso(now + timedelta(minutes=10)),
        "working_context_id": "ai-room-working-context",
        "working_context_version": "v1",
        "working_context_digest": _digest(working_context),
        "project_memory_id": "repository-project-memory",
        "project_memory_version": f"schema-{project_memory_snapshot.get('schema_version', 'unknown')}",
        "project_memory_digest": _digest(project_memory_snapshot),
        "conflict_state": "clear",
    }
    session = {
        "session_id": session_id,
        "conversation_id": conversation_id,
        "actor_id": "dashboard-owner-session",
        "turn_id": turn_id,
        "created_at": now_text,
        "current_message": classifier_message,
    }
    try:
        result = evaluate_ai_action(
            session=session,
            context=context,
            model=MODEL,
            model_output=proposal,
            tool_registry=TOOL_REGISTRY,
            policy=POLICY,
            evaluated_at=now_text,
        )
    except AIControlPlaneError as exc:
        raise AIRoomError("AI control plane rejected malformed input") from exc
    decision = asdict(result)
    return {
        "contract_version": AI_ROOM_CONTRACT_VERSION,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "intent": intent,
        "decision": decision,
        "proposal": {
            "action": proposal["action"],
            "route": decision["route"],
            "executed": False,
            "state_mutation": False,
            "paper_only": True,
        },
        "operations": operations,
        "reply": _reply(intent, decision, operations),
        "privacy": {
            "server_persisted_transcript": False,
            "external_provider_called": False,
            "history_scope": "browser_session",
            "raw_message_returned": False,
            "raw_message_digest_bound": True,
        },
    }
