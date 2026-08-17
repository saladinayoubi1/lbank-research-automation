from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

PROJECT = "NEXUS / lbank-research-automation"
SCHEMA_VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

WORKING_CONTEXT_KEYS = {
    "context_id", "conversation_id", "generated_at", "expires_at", "source_repo_sha",
    "project_memory_state_digest", "phase", "current_gate", "summary", "decisions",
    "evidence_refs", "open_blockers", "health",
}
HEALTH_KEYS = {"used_units", "capacity_units", "unresolved_conflicts", "stale_reference_count"}
POLICY_KEYS = {
    "schema_version", "max_context_age_seconds", "handoff_utilization_percent",
    "max_summary_chars", "max_decisions", "max_evidence_refs", "max_blockers",
    "max_requested_authority",
}
MIGRATION_REQUEST_KEYS = {
    "migration_id", "source_checkpoint_id", "source_checkpoint_digest", "target_conversation_id",
    "expected_repo_sha", "expected_project_memory_state_digest", "expected_evidence_refs",
    "requested_authority",
}
CHECKPOINT_KEYS = {
    "schema_version", "project", "record_type", "checkpoint_id", "created_at",
    "source_context_id", "source_conversation_id", "repo_sha", "project_memory_state_digest",
    "phase", "current_gate", "summary", "decisions", "evidence_refs", "open_blockers",
    "health_status", "health_reason", "safety", "record_digest",
}
MIGRATION_BUNDLE_KEYS = {
    "schema_version", "project", "record_type", "migration_id", "source_checkpoint_id",
    "source_checkpoint_digest", "target_conversation_id", "repo_sha",
    "project_memory_state_digest", "phase", "current_gate", "summary", "decisions",
    "evidence_refs", "open_blockers", "requested_authority", "safety", "bundle_digest",
}

_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"authorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(
        r"(?:api[_ -]?key|api[_ -]?secret|password|access[_ -]?token|refresh[_ -]?token|private[_ -]?key|seed[_ -]?phrase)"
        r"\s*[:=]\s*[\"']?[^\s\"']{8,}",
        re.IGNORECASE,
    ),
)


class HandoffValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ContextHealth:
    status: str
    reason_code: str
    utilization_percent: int


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HandoffValidationError("value is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def project_memory_state_digest(state: Mapping[str, Any]) -> str:
    if not isinstance(state, Mapping):
        raise HandoffValidationError("Project Memory state must be an object")
    return _digest(dict(state))


def _exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise HandoffValidationError(f"{name} schema mismatch")
    return dict(value)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 180:
        raise HandoffValidationError(f"{field} must be a non-empty bounded string")
    return value


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise HandoffValidationError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HandoffValidationError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise HandoffValidationError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA_RE.fullmatch(value) is None:
        raise HandoffValidationError(f"{field} must be a lowercase 40-hex SHA")
    return value


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise HandoffValidationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise HandoffValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _bounded_string(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise HandoffValidationError(f"{field} exceeds bounded length")
    _reject_sensitive(value, field)
    return value


def _safe_string_list(value: Any, field: str, maximum_items: int, *, item_max: int = 400) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > maximum_items:
        raise HandoffValidationError(f"{field} must be a bounded list")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip() or len(item) > item_max:
            raise HandoffValidationError(f"{field}[{index}] must be a non-empty bounded string")
        _reject_sensitive(item, f"{field}[{index}]")
        normalized.append(item)
    if len(set(normalized)) != len(normalized):
        raise HandoffValidationError(f"{field} contains duplicates")
    return tuple(normalized)


def _reject_sensitive(value: Any, path: str = "value") -> None:
    if isinstance(value, str):
        if any(pattern.search(value) for pattern in _SECRET_PATTERNS):
            raise HandoffValidationError(f"{path} contains sensitive authorization material")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).casefold().replace("-", "_").replace(" ", "_")
            if normalized in {
                "raw_transcript", "raw_chat", "chat_transcript", "credentials", "api_key",
                "api_secret", "private_key", "password", "access_token", "refresh_token",
                "authorization", "seed_phrase",
            }:
                raise HandoffValidationError(f"{path}.{key} is forbidden in continuity artifacts")
            _reject_sensitive(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_sensitive(child, f"{path}[{index}]")


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = _exact(policy, POLICY_KEYS, "handoff policy")
    if policy["schema_version"] != SCHEMA_VERSION:
        raise HandoffValidationError("unsupported handoff policy schema")
    _integer(policy["max_context_age_seconds"], "policy.max_context_age_seconds", minimum=1)
    threshold = _integer(policy["handoff_utilization_percent"], "policy.handoff_utilization_percent", minimum=1)
    if threshold > 100:
        raise HandoffValidationError("handoff utilization threshold must be <= 100")
    _integer(policy["max_summary_chars"], "policy.max_summary_chars", minimum=1)
    _integer(policy["max_decisions"], "policy.max_decisions", minimum=1)
    _integer(policy["max_evidence_refs"], "policy.max_evidence_refs", minimum=1)
    _integer(policy["max_blockers"], "policy.max_blockers", minimum=1)
    max_authority = _integer(policy["max_requested_authority"], "policy.max_requested_authority")
    if max_authority > 3:
        raise HandoffValidationError("handoff migration may not authorize L4")
    return policy


def _validate_memory_state(state: Mapping[str, Any], expected_repo_sha: str) -> dict[str, Any]:
    if not isinstance(state, Mapping):
        raise HandoffValidationError("Project Memory state must be an object")
    state = dict(state)
    _reject_sensitive(state, "project_memory_state")
    if state.get("project") != PROJECT:
        raise HandoffValidationError("Project Memory project identity mismatch")
    if not isinstance(state.get("schema_version"), int) or state["schema_version"] < 2:
        raise HandoffValidationError("Project Memory schema is unsupported")
    memory_policy = state.get("memory_policy")
    if not isinstance(memory_policy, Mapping):
        raise HandoffValidationError("Project Memory policy missing")
    if memory_policy.get("repository_is_durable_source") is not True:
        raise HandoffValidationError("repository must remain the durable source")
    if memory_policy.get("chat_is_source_of_truth") is not False:
        raise HandoffValidationError("chat must remain non-authoritative")
    if memory_policy.get("secrets_allowed") is not False:
        raise HandoffValidationError("Project Memory must remain secret-free")
    evidence = state.get("current_evidence")
    if not isinstance(evidence, Mapping):
        raise HandoffValidationError("Project Memory current_evidence missing")
    observed = _sha(evidence.get("observed_main_sha"), "Project Memory observed_main_sha")
    if observed != expected_repo_sha:
        raise HandoffValidationError(
            f"stale Project Memory: observed {observed}, expected {expected_repo_sha}"
        )
    return state


def validate_working_context(
    working_context: Mapping[str, Any],
    *,
    project_memory_state: Mapping[str, Any],
    expected_repo_sha: str,
    policy: Mapping[str, Any],
    evaluated_at: str,
) -> dict[str, Any]:
    policy = validate_policy(policy)
    expected_repo_sha = _sha(expected_repo_sha, "expected_repo_sha")
    state = _validate_memory_state(project_memory_state, expected_repo_sha)
    context = _exact(working_context, WORKING_CONTEXT_KEYS, "working context")
    _reject_sensitive(context, "working_context")

    _identifier(context["context_id"], "context.context_id")
    _identifier(context["conversation_id"], "context.conversation_id")
    generated = _utc(context["generated_at"], "context.generated_at")
    expires = _utc(context["expires_at"], "context.expires_at")
    now = _utc(evaluated_at, "evaluated_at")
    if generated > now:
        raise HandoffValidationError("working context timestamp is in the future")
    if expires <= generated:
        raise HandoffValidationError("working context expiry must follow generation")
    if expires <= now:
        raise HandoffValidationError("working context is expired")
    if (now - generated).total_seconds() > policy["max_context_age_seconds"]:
        raise HandoffValidationError("working context exceeds maximum age")

    if _sha(context["source_repo_sha"], "context.source_repo_sha") != expected_repo_sha:
        raise HandoffValidationError("working context repository binding mismatch")
    expected_state_digest = project_memory_state_digest(state)
    if _sha256(context["project_memory_state_digest"], "context.project_memory_state_digest") != expected_state_digest:
        raise HandoffValidationError("working context Project Memory digest mismatch")

    phase = _integer(context["phase"], "context.phase", minimum=1)
    gate = _integer(context["current_gate"], "context.current_gate")
    if gate > 99:
        raise HandoffValidationError("context.current_gate is out of range")
    _bounded_string(context["summary"], "context.summary", policy["max_summary_chars"])
    _safe_string_list(context["decisions"], "context.decisions", policy["max_decisions"])
    _safe_string_list(context["evidence_refs"], "context.evidence_refs", policy["max_evidence_refs"])
    _safe_string_list(context["open_blockers"], "context.open_blockers", policy["max_blockers"])

    health = _exact(context["health"], HEALTH_KEYS, "context health")
    used = _integer(health["used_units"], "health.used_units")
    capacity = _integer(health["capacity_units"], "health.capacity_units", minimum=1)
    if used > capacity:
        raise HandoffValidationError("working context utilization exceeds capacity")
    _integer(health["unresolved_conflicts"], "health.unresolved_conflicts")
    _integer(health["stale_reference_count"], "health.stale_reference_count")
    return context


def assess_context_health(working_context: Mapping[str, Any], policy: Mapping[str, Any]) -> ContextHealth:
    policy = validate_policy(policy)
    context = _exact(working_context, WORKING_CONTEXT_KEYS, "working context")
    health = _exact(context["health"], HEALTH_KEYS, "context health")
    used = _integer(health["used_units"], "health.used_units")
    capacity = _integer(health["capacity_units"], "health.capacity_units", minimum=1)
    conflicts = _integer(health["unresolved_conflicts"], "health.unresolved_conflicts")
    stale_refs = _integer(health["stale_reference_count"], "health.stale_reference_count")
    if used > capacity:
        raise HandoffValidationError("working context utilization exceeds capacity")
    percent = (used * 100) // capacity
    if conflicts:
        return ContextHealth("blocked", "context_conflict", percent)
    if stale_refs:
        return ContextHealth("blocked", "stale_evidence_reference", percent)
    if used * 100 >= capacity * policy["handoff_utilization_percent"]:
        return ContextHealth("handoff_required", "context_health_threshold_reached", percent)
    return ContextHealth("healthy", "below_handoff_threshold", percent)


def create_handoff_checkpoint(
    *,
    working_context: Mapping[str, Any],
    project_memory_state: Mapping[str, Any],
    expected_repo_sha: str,
    policy: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    policy = validate_policy(policy)
    context = validate_working_context(
        working_context,
        project_memory_state=project_memory_state,
        expected_repo_sha=expected_repo_sha,
        policy=policy,
        evaluated_at=created_at,
    )
    health = assess_context_health(context, policy)
    if health.status == "blocked":
        raise HandoffValidationError(f"handoff blocked: {health.reason_code}")
    if health.status != "handoff_required":
        raise HandoffValidationError("handoff threshold not reached")

    created = _utc(created_at, "created_at").isoformat().replace("+00:00", "Z")
    core = {
        "schema_version": SCHEMA_VERSION,
        "project": PROJECT,
        "record_type": "chat_handoff_checkpoint",
        "created_at": created,
        "source_context_id": context["context_id"],
        "source_conversation_id": context["conversation_id"],
        "repo_sha": context["source_repo_sha"],
        "project_memory_state_digest": context["project_memory_state_digest"],
        "phase": context["phase"],
        "current_gate": context["current_gate"],
        "summary": context["summary"],
        "decisions": list(context["decisions"]),
        "evidence_refs": list(context["evidence_refs"]),
        "open_blockers": list(context["open_blockers"]),
        "health_status": health.status,
        "health_reason": health.reason_code,
        "safety": {
            "raw_private_transcript_included": False,
            "credentials_included": False,
            "chat_authoritative": False,
            "production_authority_granted": False,
        },
    }
    checkpoint_id = f"handoff-{_digest(core)[:32]}"
    with_id = {**core, "checkpoint_id": checkpoint_id}
    checkpoint = {**with_id, "record_digest": _digest(with_id)}
    if set(checkpoint) != CHECKPOINT_KEYS:
        raise HandoffValidationError("internal checkpoint schema mismatch")
    return checkpoint


def validate_checkpoint(checkpoint: Mapping[str, Any]) -> dict[str, Any]:
    checkpoint = _exact(checkpoint, CHECKPOINT_KEYS, "checkpoint")
    _reject_sensitive(checkpoint, "checkpoint")
    if checkpoint["schema_version"] != SCHEMA_VERSION or checkpoint["project"] != PROJECT:
        raise HandoffValidationError("unsupported checkpoint identity")
    if checkpoint["record_type"] != "chat_handoff_checkpoint":
        raise HandoffValidationError("unsupported checkpoint record type")
    _identifier(checkpoint["checkpoint_id"], "checkpoint.checkpoint_id")
    _utc(checkpoint["created_at"], "checkpoint.created_at")
    _identifier(checkpoint["source_context_id"], "checkpoint.source_context_id")
    _identifier(checkpoint["source_conversation_id"], "checkpoint.source_conversation_id")
    _sha(checkpoint["repo_sha"], "checkpoint.repo_sha")
    _sha256(checkpoint["project_memory_state_digest"], "checkpoint.project_memory_state_digest")
    if checkpoint["health_status"] != "handoff_required" or checkpoint["health_reason"] != "context_health_threshold_reached":
        raise HandoffValidationError("checkpoint health trigger is invalid")
    safety = checkpoint["safety"]
    if safety != {
        "raw_private_transcript_included": False,
        "credentials_included": False,
        "chat_authoritative": False,
        "production_authority_granted": False,
    }:
        raise HandoffValidationError("checkpoint safety boundary mismatch")
    supplied = _sha256(checkpoint["record_digest"], "checkpoint.record_digest")
    body = {key: value for key, value in checkpoint.items() if key != "record_digest"}
    if supplied != _digest(body):
        raise HandoffValidationError("checkpoint digest mismatch")
    expected_id = f"handoff-{_digest({key: value for key, value in body.items() if key != 'checkpoint_id'})[:32]}"
    if checkpoint["checkpoint_id"] != expected_id:
        raise HandoffValidationError("checkpoint identity mismatch")
    return checkpoint


def prepare_chat_migration(
    *,
    checkpoint: Mapping[str, Any],
    request: Mapping[str, Any],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    policy = validate_policy(policy)
    checkpoint = validate_checkpoint(checkpoint)
    request = _exact(request, MIGRATION_REQUEST_KEYS, "migration request")
    _reject_sensitive(request, "migration_request")
    _identifier(request["migration_id"], "migration.migration_id")
    _identifier(request["target_conversation_id"], "migration.target_conversation_id")
    if request["target_conversation_id"] == checkpoint["source_conversation_id"]:
        raise HandoffValidationError("migration target must be a different conversation")
    if request["source_checkpoint_id"] != checkpoint["checkpoint_id"]:
        raise HandoffValidationError("migration checkpoint identity mismatch")
    if _sha256(request["source_checkpoint_digest"], "migration.source_checkpoint_digest") != checkpoint["record_digest"]:
        raise HandoffValidationError("migration checkpoint digest mismatch")
    if _sha(request["expected_repo_sha"], "migration.expected_repo_sha") != checkpoint["repo_sha"]:
        raise HandoffValidationError("migration repository state mismatch")
    if _sha256(
        request["expected_project_memory_state_digest"], "migration.expected_project_memory_state_digest"
    ) != checkpoint["project_memory_state_digest"]:
        raise HandoffValidationError("migration Project Memory state mismatch")
    evidence_refs = _safe_string_list(
        request["expected_evidence_refs"], "migration.expected_evidence_refs", policy["max_evidence_refs"]
    )
    if list(evidence_refs) != checkpoint["evidence_refs"]:
        raise HandoffValidationError("migration evidence references changed")
    authority = _integer(request["requested_authority"], "migration.requested_authority")
    if authority > policy["max_requested_authority"]:
        raise HandoffValidationError("migration cannot self-promote authority")

    core = {
        "schema_version": SCHEMA_VERSION,
        "project": PROJECT,
        "record_type": "chat_migration_bundle",
        "migration_id": request["migration_id"],
        "source_checkpoint_id": checkpoint["checkpoint_id"],
        "source_checkpoint_digest": checkpoint["record_digest"],
        "target_conversation_id": request["target_conversation_id"],
        "repo_sha": checkpoint["repo_sha"],
        "project_memory_state_digest": checkpoint["project_memory_state_digest"],
        "phase": checkpoint["phase"],
        "current_gate": checkpoint["current_gate"],
        "summary": checkpoint["summary"],
        "decisions": list(checkpoint["decisions"]),
        "evidence_refs": list(checkpoint["evidence_refs"]),
        "open_blockers": list(checkpoint["open_blockers"]),
        "requested_authority": authority,
        "safety": {
            "raw_private_transcript_included": False,
            "credentials_included": False,
            "chat_authoritative": False,
            "source_repo_state_preserved": True,
            "evidence_refs_preserved": True,
        },
    }
    bundle = {**core, "bundle_digest": _digest(core)}
    if set(bundle) != MIGRATION_BUNDLE_KEYS:
        raise HandoffValidationError("internal migration bundle schema mismatch")
    return bundle


def validate_migration_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    bundle = _exact(bundle, MIGRATION_BUNDLE_KEYS, "migration bundle")
    _reject_sensitive(bundle, "migration_bundle")
    if bundle["schema_version"] != SCHEMA_VERSION or bundle["project"] != PROJECT:
        raise HandoffValidationError("unsupported migration bundle identity")
    if bundle["record_type"] != "chat_migration_bundle":
        raise HandoffValidationError("unsupported migration bundle record type")
    _sha(bundle["repo_sha"], "bundle.repo_sha")
    _sha256(bundle["project_memory_state_digest"], "bundle.project_memory_state_digest")
    _sha256(bundle["source_checkpoint_digest"], "bundle.source_checkpoint_digest")
    supplied = _sha256(bundle["bundle_digest"], "bundle.bundle_digest")
    body = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    if supplied != _digest(body):
        raise HandoffValidationError("migration bundle digest mismatch")
    if bundle["safety"] != {
        "raw_private_transcript_included": False,
        "credentials_included": False,
        "chat_authoritative": False,
        "source_repo_state_preserved": True,
        "evidence_refs_preserved": True,
    }:
        raise HandoffValidationError("migration bundle safety mismatch")
    return bundle
