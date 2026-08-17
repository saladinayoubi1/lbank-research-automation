from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

SESSION_KEYS = {
    "session_id", "conversation_id", "actor_id", "turn_id", "created_at", "current_message",
}
CONTEXT_KEYS = {
    "context_id", "conversation_id", "provenance_id", "generated_at", "expires_at",
    "working_context_id", "working_context_version", "working_context_digest",
    "project_memory_id", "project_memory_version", "project_memory_digest", "conflict_state",
}
MODEL_KEYS = {"provider_id", "model_id", "model_version"}
MODEL_OUTPUT_KEYS = {
    "intent", "action", "tool", "parameters", "requested_authority", "retry_count",
    "timeout_seconds", "delegation_depth", "cancel_requested",
}
TOOL_KEYS = {
    "tool_id", "enabled", "max_authority", "reversible", "allowed_intents",
    "max_timeout_seconds",
}
POLICY_KEYS = {
    "policy_version", "max_retry_count", "max_timeout_seconds", "max_delegation_depth",
    "autonomous_authority_levels", "human_required_actions",
}

INTENT_MAX_AUTHORITY = {
    "observe": 0,
    "propose": 1,
    "paper_action": 2,
    "workflow": 3,
    "owner_sensitive": 4,
}
FORBIDDEN_TERMS = {
    "api_key", "api_secret", "credential", "private_key", "live_order", "withdrawal",
    "production", "billing", "signing", "exchange_secret", "seed_phrase",
}
SENSITIVE_ACTION_FRAGMENTS = (
    "api_key",
    "api_secret",
    "credential",
    "private_key",
    "live_order",
    "real_order",
    "live_trade",
    "real_trade",
    "withdraw",
    "production",
    "billing",
    "signing",
    "exchange_secret",
    "seed_phrase",
)
FORBIDDEN_TOOL_PREFIXES = (
    "exchange_private",
    "exchange_live",
    "wallet_withdraw",
    "production_deploy",
    "billing_",
    "signing_",
    "shell_",
)
FORBIDDEN_PARAMETER_VALUE_FRAGMENTS = (
    "api_key",
    "api_secret",
    "credential",
    "private_key",
    "live_order",
    "real_order",
    "live_trade",
    "real_trade",
    "withdrawal",
    "wallet_withdraw",
    "production_deploy",
    "production_promotion",
    "billing_authority",
    "signing_authority",
    "exchange_secret",
    "seed_phrase",
    "exchange_live",
    "exchange_private",
    "private_api",
    "private_exchange",
    "shell_exec",
)


@dataclass(frozen=True)
class ControlDecision:
    allowed: bool
    status: str
    reason_code: str
    authority_level: int
    route: str | None
    session_id: str | None
    conversation_id: str | None
    correlation_id: str
    model_provider: str | None
    model_id: str | None
    policy_version: str | None
    audit_digest: str


class AIControlPlaneError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: Any, keys: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise AIControlPlaneError(f"{name} schema mismatch")
    return value


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise AIControlPlaneError(f"{field} must be a non-empty bounded string")
    return value


def _security_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.casefold()).strip("_")


def _is_sensitive_action(value: str) -> bool:
    normalized = _security_token(value)
    return any(fragment in normalized for fragment in SENSITIVE_ACTION_FRAGMENTS)


def _is_forbidden_tool(value: str) -> bool:
    normalized = _security_token(value)
    return any(normalized.startswith(prefix) for prefix in FORBIDDEN_TOOL_PREFIXES)


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AIControlPlaneError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AIControlPlaneError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AIControlPlaneError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise AIControlPlaneError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise AIControlPlaneError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _bounded_int(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AIControlPlaneError(f"{field} must be an integer >= {minimum}")
    return value


def _reject_forbidden(value: Any, path: str = "parameters") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = _security_token(str(key))
            if normalized in FORBIDDEN_TERMS or any(term in normalized for term in FORBIDDEN_TERMS):
                raise AIControlPlaneError(f"{path}.{key} is forbidden")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")
    elif isinstance(value, str):
        normalized = _security_token(value)
        if any(fragment in normalized for fragment in FORBIDDEN_PARAMETER_VALUE_FRAGMENTS):
            raise AIControlPlaneError(f"{path} contains forbidden authority material")


def classify_intent(message: Any) -> str:
    """Deterministic coarse intent classifier used as a policy boundary, not an LLM guess."""
    if not isinstance(message, str) or not message.strip() or len(message) > 8_000:
        raise AIControlPlaneError("current_message is missing or oversized")
    text = message.casefold()
    owner_terms = ("production", "live trade", "withdraw", "billing", "sign ", "private key", "api key")
    workflow_terms = ("autonomous", "workflow", "delegate", "run all", "continue until")
    action_terms = ("paper trade", "paper order", "open position", "close position", "kill switch")
    proposal_terms = ("propose", "recommend", "plan", "draft", "suggest")
    if any(term in text for term in owner_terms):
        return "owner_sensitive"
    if any(term in text for term in workflow_terms):
        return "workflow"
    if any(term in text for term in action_terms):
        return "paper_action"
    if any(term in text for term in proposal_terms):
        return "propose"
    return "observe"


def _audit_decision(
    *,
    allowed: bool,
    status: str,
    reason_code: str,
    authority_level: int,
    route: str | None,
    session: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
    model: Mapping[str, Any] | None,
    policy: Mapping[str, Any] | None,
    model_output: Any,
    evaluated_at: str,
) -> ControlDecision:
    session_id = session.get("session_id") if isinstance(session, Mapping) else None
    conversation_id = session.get("conversation_id") if isinstance(session, Mapping) else None
    provider = model.get("provider_id") if isinstance(model, Mapping) else None
    model_id = model.get("model_id") if isinstance(model, Mapping) else None
    policy_version = policy.get("policy_version") if isinstance(policy, Mapping) else None
    correlation_id = _hash({
        "session_id": session_id,
        "conversation_id": conversation_id,
        "turn_id": session.get("turn_id") if isinstance(session, Mapping) else None,
        "evaluated_at": evaluated_at,
    })[:32]
    audit = {
        "actor": session.get("actor_id") if isinstance(session, Mapping) else None,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "turn_id": session.get("turn_id") if isinstance(session, Mapping) else None,
        "context_id": context.get("context_id") if isinstance(context, Mapping) else None,
        "working_context_id": context.get("working_context_id") if isinstance(context, Mapping) else None,
        "project_memory_id": context.get("project_memory_id") if isinstance(context, Mapping) else None,
        "model_provider": provider,
        "model_id": model_id,
        "model_version": model.get("model_version") if isinstance(model, Mapping) else None,
        "policy_version": policy_version,
        "proposal_digest": _hash(model_output) if isinstance(model_output, Mapping) else None,
        "decision": status,
        "reason_code": reason_code,
        "authority_level": authority_level,
        "route": route,
        "evaluated_at": evaluated_at,
        "correlation_id": correlation_id,
    }
    return ControlDecision(
        allowed=allowed,
        status=status,
        reason_code=reason_code,
        authority_level=authority_level,
        route=route,
        session_id=session_id,
        conversation_id=conversation_id,
        correlation_id=correlation_id,
        model_provider=provider,
        model_id=model_id,
        policy_version=policy_version,
        audit_digest=_hash(audit),
    )


def evaluate_ai_action(
    *,
    session: Mapping[str, Any],
    context: Mapping[str, Any],
    model: Mapping[str, Any],
    model_output: Mapping[str, Any],
    tool_registry: Mapping[str, Mapping[str, Any]],
    policy: Mapping[str, Any],
    evaluated_at: str,
) -> ControlDecision:
    """Validate one AI proposal and return a deterministic routing/authority decision."""
    route: str | None = None
    authority = 0
    try:
        session = dict(_exact(session, SESSION_KEYS, "session"))
        context = dict(_exact(context, CONTEXT_KEYS, "context"))
        model = dict(_exact(model, MODEL_KEYS, "model"))
        model_output = dict(_exact(model_output, MODEL_OUTPUT_KEYS, "model_output"))
        policy = dict(_exact(policy, POLICY_KEYS, "policy"))
        now = _utc(evaluated_at, "evaluated_at")

        for field in ("session_id", "conversation_id", "actor_id", "turn_id"):
            _identifier(session[field], f"session.{field}")
        created_at = _utc(session["created_at"], "session.created_at")
        if created_at > now:
            raise AIControlPlaneError("session timestamp is in the future")
        classified_intent = classify_intent(session["current_message"])

        for field in (
            "context_id", "conversation_id", "provenance_id", "working_context_id",
            "working_context_version", "project_memory_id", "project_memory_version",
        ):
            _identifier(context[field], f"context.{field}")
        _digest(context["working_context_digest"], "context.working_context_digest")
        _digest(context["project_memory_digest"], "context.project_memory_digest")
        generated = _utc(context["generated_at"], "context.generated_at")
        expires = _utc(context["expires_at"], "context.expires_at")
        if context["conversation_id"] != session["conversation_id"]:
            raise AIControlPlaneError("context conversation mismatch")
        if context["working_context_id"] == context["project_memory_id"]:
            raise AIControlPlaneError("working context and durable Project Memory must remain separate")
        if context["conflict_state"] != "clear":
            return _audit_decision(
                allowed=False, status="blocked", reason_code="context_conflict", authority_level=0,
                route=None, session=session, context=context, model=model, policy=policy,
                model_output=model_output, evaluated_at=evaluated_at,
            )
        if generated > now or expires <= now:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="stale_context", authority_level=0,
                route=None, session=session, context=context, model=model, policy=policy,
                model_output=model_output, evaluated_at=evaluated_at,
            )

        for field in MODEL_KEYS:
            _identifier(model[field], f"model.{field}")
        _identifier(policy["policy_version"], "policy.policy_version")
        max_retries = _bounded_int(policy["max_retry_count"], "policy.max_retry_count")
        max_timeout = _bounded_int(policy["max_timeout_seconds"], "policy.max_timeout_seconds", minimum=1)
        max_delegation = _bounded_int(policy["max_delegation_depth"], "policy.max_delegation_depth")
        if not isinstance(policy["autonomous_authority_levels"], list) or any(
            isinstance(level, bool) or not isinstance(level, int) or level not in {0, 1, 2, 3}
            for level in policy["autonomous_authority_levels"]
        ):
            raise AIControlPlaneError("policy autonomous authority levels are malformed")
        if not isinstance(policy["human_required_actions"], list) or any(
            not isinstance(action, str) or not action for action in policy["human_required_actions"]
        ):
            raise AIControlPlaneError("policy human-required actions are malformed")

        if model_output["intent"] not in INTENT_MAX_AUTHORITY:
            raise AIControlPlaneError("unknown model intent")
        if model_output["intent"] != classified_intent:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="intent_mismatch", authority_level=0,
                route=None, session=session, context=context, model=model, policy=policy,
                model_output=model_output, evaluated_at=evaluated_at,
            )
        action = _identifier(model_output["action"], "model_output.action")
        authority = _bounded_int(model_output["requested_authority"], "model_output.requested_authority")
        if authority > 4:
            raise AIControlPlaneError("requested authority is invalid")
        if _is_sensitive_action(action):
            return _audit_decision(
                allowed=False, status="owner_required", reason_code="human_required",
                authority_level=max(authority, 4), route=None, session=session, context=context,
                model=model, policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if authority > INTENT_MAX_AUTHORITY[classified_intent]:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="authority_self_promotion",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        retry_count = _bounded_int(model_output["retry_count"], "model_output.retry_count")
        timeout_seconds = _bounded_int(model_output["timeout_seconds"], "model_output.timeout_seconds", minimum=1)
        delegation_depth = _bounded_int(model_output["delegation_depth"], "model_output.delegation_depth")
        if retry_count > max_retries:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="retry_limit_exceeded",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if timeout_seconds > max_timeout:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="timeout_limit_exceeded",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if delegation_depth > max_delegation:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="delegation_limit_exceeded",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if not isinstance(model_output["cancel_requested"], bool):
            raise AIControlPlaneError("cancel_requested must be boolean")
        if model_output["cancel_requested"]:
            return _audit_decision(
                allowed=False, status="cancelled", reason_code="cancel_requested",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if not isinstance(model_output["parameters"], Mapping):
            raise AIControlPlaneError("parameters must be an object")
        _reject_forbidden(model_output["parameters"])

        if classified_intent == "owner_sensitive" or authority == 4 or action in policy["human_required_actions"]:
            return _audit_decision(
                allowed=False, status="owner_required", reason_code="human_required",
                authority_level=max(authority, 4 if classified_intent == "owner_sensitive" else authority),
                route=None, session=session, context=context, model=model, policy=policy,
                model_output=model_output, evaluated_at=evaluated_at,
            )

        tool_name = model_output["tool"]
        if authority <= 1:
            if tool_name is not None:
                return _audit_decision(
                    allowed=False, status="blocked", reason_code="tool_not_allowed_for_observe_propose",
                    authority_level=authority, route=None, session=session, context=context, model=model,
                    policy=policy, model_output=model_output, evaluated_at=evaluated_at,
                )
            return _audit_decision(
                allowed=True, status="allowed", reason_code="observe_or_propose_allowed",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )

        _identifier(tool_name, "model_output.tool")
        if _is_forbidden_tool(tool_name):
            return _audit_decision(
                allowed=False, status="blocked", reason_code="forbidden_tool_namespace",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if not isinstance(tool_registry, Mapping) or tool_name not in tool_registry:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="tool_not_registered",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        tool = dict(_exact(tool_registry[tool_name], TOOL_KEYS, "tool"))
        if tool["tool_id"] != tool_name:
            raise AIControlPlaneError("tool registry identity mismatch")
        if not isinstance(tool["enabled"], bool) or not isinstance(tool["reversible"], bool):
            raise AIControlPlaneError("tool flags are malformed")
        if not tool["enabled"]:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="tool_disabled",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        tool_max = _bounded_int(tool["max_authority"], "tool.max_authority")
        tool_timeout = _bounded_int(tool["max_timeout_seconds"], "tool.max_timeout_seconds", minimum=1)
        if authority > min(tool_max, 3):
            return _audit_decision(
                allowed=False, status="blocked", reason_code="tool_authority_exceeded",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if not isinstance(tool["allowed_intents"], list) or classified_intent not in tool["allowed_intents"]:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="tool_intent_denied",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if timeout_seconds > tool_timeout:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="tool_timeout_exceeded",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if authority in {2, 3} and not tool["reversible"]:
            return _audit_decision(
                allowed=False, status="blocked", reason_code="non_reversible_tool_denied",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        if authority not in policy["autonomous_authority_levels"]:
            return _audit_decision(
                allowed=False, status="owner_required", reason_code="authority_not_policy_authorized",
                authority_level=authority, route=None, session=session, context=context, model=model,
                policy=policy, model_output=model_output, evaluated_at=evaluated_at,
            )
        route = tool_name
        return _audit_decision(
            allowed=True, status="allowed", reason_code="bounded_tool_action_allowed",
            authority_level=authority, route=route, session=session, context=context, model=model,
            policy=policy, model_output=model_output, evaluated_at=evaluated_at,
        )
    except (AIControlPlaneError, TypeError, ValueError, OverflowError):
        return _audit_decision(
            allowed=False, status="blocked", reason_code="malformed_or_ambiguous_input",
            authority_level=authority, route=route, session=session if isinstance(session, Mapping) else None,
            context=context if isinstance(context, Mapping) else None,
            model=model if isinstance(model, Mapping) else None,
            policy=policy if isinstance(policy, Mapping) else None,
            model_output=model_output, evaluated_at=evaluated_at,
        )