from copy import deepcopy

import pytest

from ai_control_plane import classify_intent, evaluate_ai_action

NOW = "2026-08-17T06:30:00Z"
D1 = "a" * 64
D2 = "b" * 64


def session(message="show current paper status"):
    return {
        "session_id": "session-1",
        "conversation_id": "conversation-1",
        "actor_id": "operator-1",
        "turn_id": "turn-7",
        "created_at": "2026-08-17T06:00:00Z",
        "current_message": message,
    }


def context(**changes):
    value = {
        "context_id": "context-7",
        "conversation_id": "conversation-1",
        "provenance_id": "project-memory-state-120",
        "generated_at": "2026-08-17T06:20:00Z",
        "expires_at": "2026-08-17T06:40:00Z",
        "working_context_id": "working-7",
        "working_context_version": "7",
        "working_context_digest": D1,
        "project_memory_id": "memory-main",
        "project_memory_version": "120",
        "project_memory_digest": D2,
        "conflict_state": "clear",
    }
    value.update(changes)
    return value


def model(**changes):
    value = {
        "provider_id": "openai",
        "model_id": "gpt-5.6-sol",
        "model_version": "2026-08-17",
    }
    value.update(changes)
    return value


def output(**changes):
    value = {
        "intent": "observe",
        "action": "inspect_status",
        "tool": None,
        "parameters": {},
        "requested_authority": 0,
        "retry_count": 0,
        "timeout_seconds": 30,
        "delegation_depth": 0,
        "cancel_requested": False,
    }
    value.update(changes)
    return value


def tool(tool_id="paper-command", **changes):
    value = {
        "tool_id": tool_id,
        "enabled": True,
        "max_authority": 2,
        "reversible": True,
        "allowed_intents": ["paper_action"],
        "max_timeout_seconds": 60,
    }
    value.update(changes)
    return value


def tools(**entries):
    base = {
        "paper-command": tool(),
        "mission-runner": tool(
            "mission-runner",
            max_authority=3,
            allowed_intents=["workflow"],
            max_timeout_seconds=120,
        ),
    }
    base.update(entries)
    return base


def policy(**changes):
    value = {
        "policy_version": "ai-policy-1.0.0",
        "max_retry_count": 1,
        "max_timeout_seconds": 120,
        "max_delegation_depth": 2,
        "autonomous_authority_levels": [0, 1, 2, 3],
        "human_required_actions": ["rotate_credentials", "promote_production"],
    }
    value.update(changes)
    return value


def evaluate(**changes):
    args = {
        "session": session(),
        "context": context(),
        "model": model(),
        "model_output": output(),
        "tool_registry": tools(),
        "policy": policy(),
        "evaluated_at": NOW,
    }
    args.update(changes)
    return evaluate_ai_action(**args)


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("show current status", "observe"),
        ("recommend a plan", "propose"),
        ("open position in paper trade", "paper_action"),
        ("continue until this workflow is done", "workflow"),
        ("promote to production", "owner_sensitive"),
    ],
)
def test_intent_classifier_is_deterministic(message, intent):
    assert classify_intent(message) == intent
    assert classify_intent(message) == intent


def test_observe_and_propose_are_allowed_without_tool_authority():
    observe = evaluate()
    assert observe.allowed is True
    assert observe.reason_code == "observe_or_propose_allowed"
    assert observe.authority_level == 0
    assert observe.route is None

    propose = evaluate(
        session=session("recommend a plan"),
        model_output=output(intent="propose", action="draft_plan", requested_authority=1),
    )
    assert propose.allowed is True
    assert propose.authority_level == 1
    assert propose.route is None


def test_l2_paper_action_routes_only_through_registered_reversible_tool():
    result = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action",
            action="submit_paper_proposal",
            tool="paper-command",
            requested_authority=2,
            parameters={"symbol": "BTCUSDT", "side": "long"},
        ),
    )
    assert result.allowed is True
    assert result.reason_code == "bounded_tool_action_allowed"
    assert result.route == "paper-command"
    assert result.authority_level == 2


def test_l3_workflow_requires_explicit_policy_and_registered_route():
    result = evaluate(
        session=session("continue until this workflow is done"),
        model_output=output(
            intent="workflow",
            action="run_bounded_mission",
            tool="mission-runner",
            requested_authority=3,
            timeout_seconds=90,
            delegation_depth=2,
        ),
    )
    assert result.allowed is True
    assert result.route == "mission-runner"

    denied = evaluate(
        session=session("continue until this workflow is done"),
        model_output=output(
            intent="workflow",
            action="run_bounded_mission",
            tool="mission-runner",
            requested_authority=3,
            timeout_seconds=90,
        ),
        policy=policy(autonomous_authority_levels=[0, 1, 2]),
    )
    assert denied.allowed is False
    assert denied.status == "owner_required"
    assert denied.reason_code == "authority_not_policy_authorized"


def test_owner_sensitive_and_l4_always_escalate():
    result = evaluate(
        session=session("promote to production"),
        model_output=output(
            intent="owner_sensitive",
            action="promote_production",
            requested_authority=4,
        ),
    )
    assert result.allowed is False
    assert result.status == "owner_required"
    assert result.reason_code == "human_required"
    assert result.authority_level == 4


def test_stale_conflicting_or_cross_conversation_context_fails_closed():
    stale = evaluate(context=context(expires_at="2026-08-17T06:29:59Z"))
    assert stale.allowed is False
    assert stale.reason_code == "stale_context"

    conflict = evaluate(context=context(conflict_state="conflicting"))
    assert conflict.allowed is False
    assert conflict.reason_code == "context_conflict"

    mismatch = evaluate(context=context(conversation_id="conversation-other"))
    assert mismatch.allowed is False
    assert mismatch.reason_code == "malformed_or_ambiguous_input"


def test_working_context_and_project_memory_must_be_separate():
    result = evaluate(context=context(project_memory_id="working-7"))
    assert result.allowed is False
    assert result.reason_code == "malformed_or_ambiguous_input"


def test_model_intent_cannot_override_deterministic_classification():
    result = evaluate(
        session=session("show current status"),
        model_output=output(intent="workflow", requested_authority=3, tool="mission-runner"),
    )
    assert result.allowed is False
    assert result.reason_code == "intent_mismatch"


def test_model_cannot_self_promote_authority():
    result = evaluate(
        session=session("recommend a plan"),
        model_output=output(intent="propose", requested_authority=2),
    )
    assert result.allowed is False
    assert result.reason_code == "authority_self_promotion"


def test_retry_timeout_delegation_and_cancel_are_bounded():
    retry = evaluate(model_output=output(retry_count=2))
    assert retry.reason_code == "retry_limit_exceeded"

    timeout = evaluate(model_output=output(timeout_seconds=121))
    assert timeout.reason_code == "timeout_limit_exceeded"

    delegation = evaluate(model_output=output(delegation_depth=3))
    assert delegation.reason_code == "delegation_limit_exceeded"

    cancelled = evaluate(model_output=output(cancel_requested=True))
    assert cancelled.status == "cancelled"
    assert cancelled.reason_code == "cancel_requested"


def test_tool_registry_permissions_fail_closed():
    unregistered = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action", action="submit_paper_proposal", tool="missing",
            requested_authority=2,
        ),
    )
    assert unregistered.reason_code == "tool_not_registered"

    disabled = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action", action="submit_paper_proposal", tool="paper-command",
            requested_authority=2,
        ),
        tool_registry={"paper-command": tool(enabled=False)},
    )
    assert disabled.reason_code == "tool_disabled"

    irreversible = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action", action="submit_paper_proposal", tool="paper-command",
            requested_authority=2,
        ),
        tool_registry={"paper-command": tool(reversible=False)},
    )
    assert irreversible.reason_code == "non_reversible_tool_denied"

    tool_timeout = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action", action="submit_paper_proposal", tool="paper-command",
            requested_authority=2, timeout_seconds=61,
        ),
    )
    assert tool_timeout.reason_code == "tool_timeout_exceeded"


def test_live_secret_and_irreversible_parameters_are_rejected_before_routing():
    result = evaluate(
        session=session("open position in paper trade"),
        model_output=output(
            intent="paper_action",
            action="submit_paper_proposal",
            tool="paper-command",
            requested_authority=2,
            parameters={"api_key": "secret"},
        ),
    )
    assert result.allowed is False
    assert result.reason_code == "malformed_or_ambiguous_input"


def test_observe_or_propose_cannot_smuggle_a_tool_call():
    result = evaluate(model_output=output(tool="paper-command"))
    assert result.allowed is False
    assert result.reason_code == "tool_not_allowed_for_observe_propose"


def test_malformed_model_output_fails_closed_instead_of_executing():
    malformed = output()
    malformed["unexpected"] = True
    result = evaluate(model_output=malformed)
    assert result.allowed is False
    assert result.reason_code == "malformed_or_ambiguous_input"
    assert result.route is None


def test_audit_binds_session_context_model_policy_and_is_deterministic():
    args = {
        "session": session("open position in paper trade"),
        "context": context(),
        "model": model(),
        "model_output": output(
            intent="paper_action", action="submit_paper_proposal", tool="paper-command",
            requested_authority=2,
        ),
        "tool_registry": tools(),
        "policy": policy(),
        "evaluated_at": NOW,
    }
    original = deepcopy(args)
    first = evaluate_ai_action(**args)
    second = evaluate_ai_action(**args)
    assert first == second
    assert args == original
    assert first.session_id == "session-1"
    assert first.conversation_id == "conversation-1"
    assert first.model_provider == "openai"
    assert first.model_id == "gpt-5.6-sol"
    assert first.policy_version == "ai-policy-1.0.0"
    assert len(first.audit_digest) == 64
    assert len(first.correlation_id) == 32
