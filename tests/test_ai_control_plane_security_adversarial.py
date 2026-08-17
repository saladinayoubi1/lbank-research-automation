from __future__ import annotations

import pytest

from ai_control_plane import evaluate_ai_action

NOW = "2026-08-17T06:30:00Z"


def _session(message: str = "continue until this workflow is done") -> dict:
    return {
        "session_id": "security-session",
        "conversation_id": "security-conversation",
        "actor_id": "operator",
        "turn_id": "turn-security",
        "created_at": "2026-08-17T06:00:00Z",
        "current_message": message,
    }


def _context() -> dict:
    return {
        "context_id": "security-context",
        "conversation_id": "security-conversation",
        "provenance_id": "project-memory",
        "generated_at": "2026-08-17T06:20:00Z",
        "expires_at": "2026-08-17T06:40:00Z",
        "working_context_id": "working-security",
        "working_context_version": "1",
        "working_context_digest": "a" * 64,
        "project_memory_id": "memory-security",
        "project_memory_version": "1",
        "project_memory_digest": "b" * 64,
        "conflict_state": "clear",
    }


def _model() -> dict:
    return {
        "provider_id": "openai",
        "model_id": "gpt-5.6-sol",
        "model_version": "security-test",
    }


def _tool(tool_id: str = "mission-runner") -> dict:
    return {
        "tool_id": tool_id,
        "enabled": True,
        "max_authority": 3,
        "reversible": True,
        "allowed_intents": ["workflow"],
        "max_timeout_seconds": 120,
    }


def _policy() -> dict:
    return {
        "policy_version": "security-policy",
        "max_retry_count": 1,
        "max_timeout_seconds": 120,
        "max_delegation_depth": 2,
        "autonomous_authority_levels": [0, 1, 2, 3],
        "human_required_actions": ["rotate_credentials", "promote_production"],
    }


def _evaluate(*, action: str = "run_bounded_mission", tool_name: str = "mission-runner", parameters=None, registry=None):
    return evaluate_ai_action(
        session=_session(),
        context=_context(),
        model=_model(),
        model_output={
            "intent": "workflow",
            "action": action,
            "tool": tool_name,
            "parameters": {} if parameters is None else parameters,
            "requested_authority": 3,
            "retry_count": 0,
            "timeout_seconds": 90,
            "delegation_depth": 1,
            "cancel_requested": False,
        },
        tool_registry={"mission-runner": _tool()} if registry is None else registry,
        policy=_policy(),
        evaluated_at=NOW,
    )


@pytest.mark.parametrize(
    "action",
    [
        "production_deploy",
        "production-promotion",
        "wallet_withdraw",
        "live/order",
        "real_trade_execute",
        "rotate_api_key",
        "load_private_key",
        "billing_authority_change",
        "signing_release",
    ],
)
def test_workflow_intent_cannot_disguise_owner_sensitive_action(action):
    result = _evaluate(action=action)
    assert result.allowed is False
    assert result.status == "owner_required"
    assert result.reason_code == "human_required"
    assert result.route is None
    assert result.authority_level == 4


@pytest.mark.parametrize(
    "tool_name",
    [
        "exchange.live.place_order",
        "exchange/private/place_order",
        "wallet.withdraw.usdt",
        "production.deploy.release",
        "billing.change_plan",
        "signing.sign_release",
        "shell.exec",
    ],
)
def test_poisoned_registry_cannot_allow_forbidden_authority_namespace(tool_name):
    result = _evaluate(
        tool_name=tool_name,
        registry={tool_name: _tool(tool_name)},
    )
    assert result.allowed is False
    assert result.status == "blocked"
    assert result.reason_code == "forbidden_tool_namespace"
    assert result.route is None


@pytest.mark.parametrize(
    "value",
    [
        "exchange.live.place_order",
        "exchange/private/place_order",
        "wallet.withdraw.usdt",
        "production deploy release",
        "production-promotion",
        "live_order",
        "real-trade",
        "api-key=opaque-secret",
        "seed phrase material",
        "shell.exec",
    ],
)
def test_registered_bounded_tool_cannot_smuggle_sensitive_authority_in_parameter_values(value):
    result = _evaluate(parameters={"target": value})
    assert result.allowed is False
    assert result.status == "blocked"
    assert result.reason_code == "malformed_or_ambiguous_input"
    assert result.route is None


def test_legitimate_bounded_workflow_route_still_passes_after_hardening():
    result = _evaluate(parameters={"mission_id": "phase4-gate20", "mode": "bounded"})
    assert result.allowed is True
    assert result.status == "allowed"
    assert result.reason_code == "bounded_tool_action_allowed"
    assert result.route == "mission-runner"
    assert result.authority_level == 3
