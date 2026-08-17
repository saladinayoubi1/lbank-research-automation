from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

ATTEMPT_SCHEMA = "nexus.phase5-attempt.v1"
RESULT_SCHEMA = "nexus.phase5-attempt-result.v1"
MAX_TASK_ATTEMPTS = 32
MAX_RESULT_BYTES = 256_000
ACTIVE_ATTEMPT_STATES = {"ISSUED"}


class AttemptError(RuntimeError):
    pass


class StaleAttempt(AttemptError):
    pass


class AttemptConflict(AttemptError):
    pass


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded_string(value: Any, field: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise AttemptError(f"{field} must be a non-empty bounded string")
    return value


def _sha(payload: Any, *, max_bytes: int | None = None) -> str:
    try:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AttemptError("attempt payload is not canonical JSON") from exc
    if max_bytes is not None and len(raw) > max_bytes:
        raise AttemptError("attempt payload exceeds bounded size")
    return hashlib.sha256(raw).hexdigest()


def _validate_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise AttemptError(f"{field} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise AttemptError(f"{field} must be a SHA-256 hex digest") from exc
    return value.lower()


def _history(task: dict[str, Any]) -> list[dict[str, Any]]:
    history = task.setdefault("attempt_history", [])
    if not isinstance(history, list):
        raise AttemptError("attempt_history must be a list")
    if len(history) > MAX_TASK_ATTEMPTS:
        raise AttemptError("attempt history exceeds bounded size")
    for item in history:
        if not isinstance(item, dict) or item.get("schema_version") != ATTEMPT_SCHEMA:
            raise AttemptError("attempt history contains malformed entries")
    return history


def _current_record(task: dict[str, Any]) -> dict[str, Any] | None:
    active_id = task.get("active_attempt_id")
    if active_id is None:
        return None
    for record in reversed(_history(task)):
        if record.get("attempt_id") == active_id:
            return record
    raise AttemptError("active_attempt_id has no matching history entry")


def begin_attempt(
    task: dict[str, Any],
    *,
    worker_id: str,
    lease_id: str,
    source_sha: str,
    state_generation: int,
) -> dict[str, Any]:
    """Issue or idempotently return the current fenced task attempt.

    A new lease/worker issuance supersedes the prior attempt and increments the
    per-task fence generation. Results from any lower fence are permanently stale.
    """
    _bounded_string(task.get("mission_id"), "mission_id")
    task_id = _bounded_string(task.get("id"), "task_id")
    spec_digest = _validate_digest(task.get("spec_digest"), "spec_digest")
    worker_id = _bounded_string(worker_id, "worker_id")
    lease_id = _bounded_string(lease_id, "lease_id")
    source_sha = _validate_digest(source_sha, "source_sha")
    if isinstance(state_generation, bool) or not isinstance(state_generation, int) or state_generation < 0:
        raise AttemptError("state_generation must be a non-negative integer")
    if int(task.get("authority", 0)) >= 4:
        raise AttemptError("L4 tasks cannot receive autonomous attempts")

    history = _history(task)
    current = _current_record(task)
    if current and current.get("status") in ACTIVE_ATTEMPT_STATES:
        if (
            current.get("worker_id") == worker_id
            and current.get("lease_id") == lease_id
            and current.get("spec_digest") == spec_digest
            and current.get("source_sha") == source_sha
        ):
            return deepcopy(current)

    # Capacity denial must not mutate the current valid attempt. This keeps a
    # bounded-retry rejection fail-closed and side-effect free.
    if len(history) >= MAX_TASK_ATTEMPTS:
        raise AttemptError("task reached bounded attempt limit")

    if current and current.get("status") in ACTIVE_ATTEMPT_STATES:
        current["status"] = "SUPERSEDED"
        current["superseded_at"] = _utcnow()

    previous_fence = task.get("fence_generation", 0)
    if isinstance(previous_fence, bool) or not isinstance(previous_fence, int) or previous_fence < 0:
        raise AttemptError("fence_generation is invalid")
    fence_generation = previous_fence + 1
    attempt_number = len(history) + 1
    identity_payload = {
        "schema_version": ATTEMPT_SCHEMA,
        "mission_id": task["mission_id"],
        "task_id": task_id,
        "spec_digest": spec_digest,
        "attempt_number": attempt_number,
        "fence_generation": fence_generation,
        "lease_id": lease_id,
        "worker_id": worker_id,
        "source_sha": source_sha,
    }
    attempt_id = _sha(identity_payload)
    record = {
        **identity_payload,
        "attempt_id": attempt_id,
        "state_generation_issued": state_generation,
        "status": "ISSUED",
        "issued_at": _utcnow(),
    }
    history.append(record)
    task["fence_generation"] = fence_generation
    task["active_attempt_id"] = attempt_id
    task["attempt"] = attempt_number
    return deepcopy(record)


def build_result(
    attempt: dict[str, Any],
    *,
    outcome: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if attempt.get("schema_version") != ATTEMPT_SCHEMA:
        raise AttemptError("attempt schema mismatch")
    if outcome not in {"success", "failure"}:
        raise AttemptError("outcome must be success or failure")
    if not isinstance(evidence, dict):
        raise AttemptError("result evidence must be an object")
    _sha(evidence, max_bytes=MAX_RESULT_BYTES)
    return {
        "schema_version": RESULT_SCHEMA,
        "mission_id": attempt["mission_id"],
        "task_id": attempt["task_id"],
        "spec_digest": attempt["spec_digest"],
        "attempt_id": attempt["attempt_id"],
        "attempt_number": attempt["attempt_number"],
        "fence_generation": attempt["fence_generation"],
        "lease_id": attempt["lease_id"],
        "worker_id": attempt["worker_id"],
        "source_sha": attempt["source_sha"],
        "outcome": outcome,
        "evidence": deepcopy(evidence),
    }


def accept_result(task: dict[str, Any], result: dict[str, Any]) -> bool:
    """Accept one result exactly once; exact duplicate delivery is a no-op.

    Returns True only for the first accepted delivery. A stale/superseded fence,
    mismatched spec/source/lease/worker or conflicting replay fails closed.
    """
    if not isinstance(result, dict):
        raise AttemptError("result root must be an object")
    required = {
        "schema_version", "mission_id", "task_id", "spec_digest", "attempt_id",
        "attempt_number", "fence_generation", "lease_id", "worker_id", "source_sha",
        "outcome", "evidence",
    }
    if set(result) != required or result.get("schema_version") != RESULT_SCHEMA:
        raise AttemptError("result schema mismatch")
    if result.get("outcome") not in {"success", "failure"} or not isinstance(result.get("evidence"), dict):
        raise AttemptError("result outcome/evidence is invalid")
    result_digest = _sha(result, max_bytes=MAX_RESULT_BYTES)

    current = _current_record(task)
    if current is None:
        raise StaleAttempt("task has no active attempt")
    current_fence = task.get("fence_generation")
    if result.get("fence_generation") != current_fence or result.get("attempt_id") != task.get("active_attempt_id"):
        raise StaleAttempt("result fence is stale")

    expected = {
        "mission_id": task.get("mission_id"),
        "task_id": task.get("id"),
        "spec_digest": task.get("spec_digest"),
        "attempt_id": current.get("attempt_id"),
        "attempt_number": current.get("attempt_number"),
        "fence_generation": current.get("fence_generation"),
        "lease_id": current.get("lease_id"),
        "worker_id": current.get("worker_id"),
        "source_sha": current.get("source_sha"),
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise StaleAttempt(f"result {field} does not match current fenced attempt")

    if current.get("status") == "INGESTED":
        if current.get("result_digest") == result_digest:
            return False
        raise AttemptConflict("attempt already has a different ingested result")
    if current.get("status") != "ISSUED":
        raise StaleAttempt("attempt is no longer active")

    current["status"] = "INGESTED"
    current["outcome"] = result["outcome"]
    current["result_digest"] = result_digest
    current["evidence_digest"] = _sha(result["evidence"], max_bytes=MAX_RESULT_BYTES)
    current["ingested_at"] = _utcnow()
    task["last_attempt_result"] = {
        "attempt_id": current["attempt_id"],
        "fence_generation": current["fence_generation"],
        "outcome": current["outcome"],
        "result_digest": current["result_digest"],
        "evidence_digest": current["evidence_digest"],
    }
    return True
