from copy import deepcopy

import pytest

from project_memory_handoff import (
    HandoffValidationError,
    assess_context_health,
    create_handoff_checkpoint,
    prepare_chat_migration,
    project_memory_state_digest,
    validate_checkpoint,
    validate_migration_bundle,
    validate_working_context,
)

REPO_SHA = "a" * 40
NOW = "2026-08-17T07:10:00Z"


def memory_state(**changes):
    state = {
        "schema_version": 2,
        "project": "NEXUS / lbank-research-automation",
        "memory_policy": {
            "repository_is_durable_source": True,
            "chat_is_source_of_truth": False,
            "secrets_allowed": False,
            "core_goals_agent_editable": False,
        },
        "current_evidence": {
            "observed_main_sha": REPO_SHA,
            "observed_at_utc": "2026-08-17T07:00:00Z",
            "active_blockers": [510],
        },
        "continuity": {
            "required_reads": [
                "docs/project_memory/PROJECT_MEMORY.md",
                "docs/project_memory/STATE.json",
            ]
        },
    }
    state.update(changes)
    return state


def policy(**changes):
    value = {
        "schema_version": 1,
        "max_context_age_seconds": 3600,
        "handoff_utilization_percent": 80,
        "max_summary_chars": 2000,
        "max_decisions": 20,
        "max_evidence_refs": 30,
        "max_blockers": 20,
        "max_requested_authority": 3,
    }
    value.update(changes)
    return value


def context(state=None, **changes):
    state = state or memory_state()
    value = {
        "context_id": "working-context-12",
        "conversation_id": "chat-old",
        "generated_at": "2026-08-17T07:00:00Z",
        "expires_at": "2026-08-17T07:30:00Z",
        "source_repo_sha": REPO_SHA,
        "project_memory_state_digest": project_memory_state_digest(state),
        "phase": 4,
        "current_gate": 12,
        "summary": "Gate 12 is implementing deterministic Project Memory handoff.",
        "decisions": [
            "Repository Project Memory stays authoritative.",
            "Working chat context is short-lived and non-authoritative.",
        ],
        "evidence_refs": [
            "main@" + REPO_SHA,
            "issue#510",
            "PR#541 merged",
        ],
        "open_blockers": ["Gate 12 acceptance pending"],
        "health": {
            "used_units": 82,
            "capacity_units": 100,
            "unresolved_conflicts": 0,
            "stale_reference_count": 0,
        },
    }
    value.update(changes)
    return value


def checkpoint(state=None, ctx=None):
    state = state or memory_state()
    ctx = ctx or context(state)
    return create_handoff_checkpoint(
        working_context=ctx,
        project_memory_state=state,
        expected_repo_sha=REPO_SHA,
        policy=policy(),
        created_at=NOW,
    )


def migration_request(cp, **changes):
    value = {
        "migration_id": "migration-12",
        "source_checkpoint_id": cp["checkpoint_id"],
        "source_checkpoint_digest": cp["record_digest"],
        "target_conversation_id": "chat-new",
        "expected_repo_sha": cp["repo_sha"],
        "expected_project_memory_state_digest": cp["project_memory_state_digest"],
        "expected_evidence_refs": list(cp["evidence_refs"]),
        "requested_authority": 2,
    }
    value.update(changes)
    return value


def test_context_health_threshold_deterministically_requires_handoff():
    health = assess_context_health(context(), policy())
    assert health.status == "handoff_required"
    assert health.reason_code == "context_health_threshold_reached"
    assert health.utilization_percent == 82

    healthy = assess_context_health(
        context(health={"used_units": 79, "capacity_units": 100, "unresolved_conflicts": 0, "stale_reference_count": 0}),
        policy(),
    )
    assert healthy.status == "healthy"
    assert healthy.reason_code == "below_handoff_threshold"


def test_conflicting_or_stale_references_block_handoff_even_at_threshold():
    conflict = context(health={"used_units": 90, "capacity_units": 100, "unresolved_conflicts": 1, "stale_reference_count": 0})
    assert assess_context_health(conflict, policy()).reason_code == "context_conflict"
    with pytest.raises(HandoffValidationError, match="context_conflict"):
        checkpoint(ctx=conflict)

    stale = context(health={"used_units": 90, "capacity_units": 100, "unresolved_conflicts": 0, "stale_reference_count": 1})
    assert assess_context_health(stale, policy()).reason_code == "stale_evidence_reference"
    with pytest.raises(HandoffValidationError, match="stale_evidence_reference"):
        checkpoint(ctx=stale)


def test_short_lived_working_context_expiry_fails_closed():
    state = memory_state()
    expired = context(state, expires_at="2026-08-17T07:09:59Z")
    with pytest.raises(HandoffValidationError, match="expired"):
        validate_working_context(
            expired,
            project_memory_state=state,
            expected_repo_sha=REPO_SHA,
            policy=policy(),
            evaluated_at=NOW,
        )


def test_stale_project_memory_repo_binding_fails_closed():
    stale_state = memory_state(
        current_evidence={
            "observed_main_sha": "b" * 40,
            "observed_at_utc": "2026-08-17T07:00:00Z",
            "active_blockers": [510],
        }
    )
    with pytest.raises(HandoffValidationError, match="stale Project Memory"):
        validate_working_context(
            context(stale_state),
            project_memory_state=stale_state,
            expected_repo_sha=REPO_SHA,
            policy=policy(),
            evaluated_at=NOW,
        )


def test_working_context_digest_must_bind_exact_durable_state():
    state = memory_state()
    changed = deepcopy(state)
    changed["current_evidence"]["active_blockers"] = [510, 999]
    with pytest.raises(HandoffValidationError, match="digest mismatch"):
        validate_working_context(
            context(state),
            project_memory_state=changed,
            expected_repo_sha=REPO_SHA,
            policy=policy(),
            evaluated_at=NOW,
        )


def test_raw_transcript_unknown_field_is_rejected_by_exact_schema():
    state = memory_state()
    value = context(state)
    value["raw_transcript"] = "private chat content"
    with pytest.raises(HandoffValidationError, match="schema mismatch"):
        validate_working_context(
            value,
            project_memory_state=state,
            expected_repo_sha=REPO_SHA,
            policy=policy(),
            evaluated_at=NOW,
        )


def test_secret_material_is_rejected_even_inside_allowed_summary():
    state = memory_state()
    value = context(state, summary="api_key=abcdefghijklmnop")
    with pytest.raises(HandoffValidationError, match="sensitive authorization material"):
        validate_working_context(
            value,
            project_memory_state=state,
            expected_repo_sha=REPO_SHA,
            policy=policy(),
            evaluated_at=NOW,
        )


def test_checkpoint_contains_only_structured_continuity_and_is_deterministic():
    state = memory_state()
    ctx = context(state)
    first = checkpoint(state, ctx)
    second = checkpoint(deepcopy(state), deepcopy(ctx))
    assert first == second
    assert first["record_type"] == "chat_handoff_checkpoint"
    assert first["repo_sha"] == REPO_SHA
    assert first["project_memory_state_digest"] == project_memory_state_digest(state)
    assert first["health_status"] == "handoff_required"
    assert first["safety"]["raw_private_transcript_included"] is False
    assert first["safety"]["credentials_included"] is False
    assert "raw_transcript" not in first
    assert validate_checkpoint(first) == first


def test_checkpoint_cannot_be_created_below_threshold():
    state = memory_state()
    ctx = context(state, health={"used_units": 50, "capacity_units": 100, "unresolved_conflicts": 0, "stale_reference_count": 0})
    with pytest.raises(HandoffValidationError, match="threshold not reached"):
        checkpoint(state, ctx)


def test_checkpoint_tampering_is_detected():
    cp = checkpoint()
    tampered = deepcopy(cp)
    tampered["summary"] = "changed after checkpoint"
    with pytest.raises(HandoffValidationError, match="digest mismatch"):
        validate_checkpoint(tampered)


def test_migration_preserves_repo_state_state_digest_and_exact_evidence_refs():
    cp = checkpoint()
    request = migration_request(cp)
    bundle = prepare_chat_migration(checkpoint=cp, request=request, policy=policy())
    assert bundle["repo_sha"] == cp["repo_sha"]
    assert bundle["project_memory_state_digest"] == cp["project_memory_state_digest"]
    assert bundle["evidence_refs"] == cp["evidence_refs"]
    assert bundle["summary"] == cp["summary"]
    assert bundle["decisions"] == cp["decisions"]
    assert bundle["safety"]["source_repo_state_preserved"] is True
    assert bundle["safety"]["evidence_refs_preserved"] is True
    assert validate_migration_bundle(bundle) == bundle


def test_migration_wrong_repo_state_or_evidence_is_blocked():
    cp = checkpoint()
    with pytest.raises(HandoffValidationError, match="repository state mismatch"):
        prepare_chat_migration(
            checkpoint=cp,
            request=migration_request(cp, expected_repo_sha="c" * 40),
            policy=policy(),
        )
    with pytest.raises(HandoffValidationError, match="evidence references changed"):
        prepare_chat_migration(
            checkpoint=cp,
            request=migration_request(cp, expected_evidence_refs=["issue#510"]),
            policy=policy(),
        )


def test_migration_cannot_self_promote_authority_or_target_same_chat():
    cp = checkpoint()
    with pytest.raises(HandoffValidationError, match="self-promote"):
        prepare_chat_migration(
            checkpoint=cp,
            request=migration_request(cp, requested_authority=4),
            policy=policy(),
        )
    with pytest.raises(HandoffValidationError, match="different conversation"):
        prepare_chat_migration(
            checkpoint=cp,
            request=migration_request(cp, target_conversation_id=cp["source_conversation_id"]),
            policy=policy(),
        )


def test_migration_request_rejects_credential_or_raw_chat_fields():
    cp = checkpoint()
    request = migration_request(cp)
    request["authorization"] = "Bearer secret"
    with pytest.raises(HandoffValidationError, match="schema mismatch"):
        prepare_chat_migration(checkpoint=cp, request=request, policy=policy())


def test_same_checkpoint_and_request_produce_same_migration_bundle_without_mutation():
    cp = checkpoint()
    request = migration_request(cp)
    original_cp = deepcopy(cp)
    original_request = deepcopy(request)
    first = prepare_chat_migration(checkpoint=cp, request=request, policy=policy())
    second = prepare_chat_migration(checkpoint=cp, request=request, policy=policy())
    assert first == second
    assert cp == original_cp
    assert request == original_request
