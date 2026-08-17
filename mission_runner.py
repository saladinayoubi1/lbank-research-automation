"""Deterministic read-only orchestration over the authoritative Mission Control projection.

The runner consumes the Gate 13 ``nexus.mission-control.read.v1`` projection. It does
not read the legacy static mission queue, execute shell commands/workers/trading code,
or persist state. L3 execution therefore means computing a bounded orchestration plan
that is cryptographically bound to the durable Mission Control state digest.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Mapping

MISSION_RUNNER_CONTRACT_VERSION = "nexus.mission-runner.v2"
MISSION_CONTROL_CONTRACT_VERSION = "nexus.mission-control.read.v1"
MAX_PROJECTION_BYTES = 256_000
MAX_QUEUE_TOTAL = 10_000
MAX_LIST_ITEMS = 256
MAX_TEXT = 180
ROOT_KEYS = {
    "contract_version", "mission", "queue", "agents", "runners", "local_node",
    "data", "providers", "paper", "circuits", "limits", "notifications",
}
MISSION_KEYS = {"mission_id", "title", "status", "priority", "deadline_at", "state_digest"}
QUEUE_KEYS = {"counts", "total"}
CIRCUIT_KEYS = {"provider", "data", "strategy", "risk"}
LIMIT_KEYS = {"resource_limited", "budget_limited"}
ACTIVE_STATUSES = {"PENDING", "READY", "RUNNING"}
TERMINAL_STATUSES = {"DONE", "CANCELLED", "FAILED"}
SUPPORTED_STATUSES = ACTIVE_STATUSES | TERMINAL_STATUSES | {"BLOCKED", "OWNER_REQUIRED", "PAUSED"}


class MissionRunnerError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise MissionRunnerError("Mission Control projection is not canonically serializable") from exc
    if len(payload) > MAX_PROJECTION_BYTES:
        raise MissionRunnerError("Mission Control projection exceeds bounded size")
    return payload


def _exact(value: Any, keys: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise MissionRunnerError(f"{field} schema mismatch")
    return dict(value)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_TEXT:
        raise MissionRunnerError(f"{field} must be a non-empty bounded string")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MissionRunnerError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise MissionRunnerError(f"{field} exceeds bound")
    return value


def _sha256(value: Any, field: str) -> str:
    value = _text(value, field)
    if len(value) != 64:
        raise MissionRunnerError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise MissionRunnerError(f"{field} must be hexadecimal") from exc
    return value.lower()


def _utc(value: Any, field: str) -> str:
    value = _text(value, field)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MissionRunnerError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise MissionRunnerError(f"{field} must be UTC")
    return value


def _bounded_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
        raise MissionRunnerError(f"{field} must be a bounded list")
    return [_text(item, field) for item in value]


def validate_projection(projection: Mapping[str, Any]) -> dict[str, Any]:
    projection = _exact(projection, ROOT_KEYS, "Mission Control projection")
    if projection["contract_version"] != MISSION_CONTROL_CONTRACT_VERSION:
        raise MissionRunnerError("Mission Control projection contract mismatch")
    _canonical(projection)

    mission = _exact(projection["mission"], MISSION_KEYS, "mission")
    mission_id = _text(mission["mission_id"], "mission.mission_id")
    _text(mission["title"], "mission.title")
    status = _text(mission["status"], "mission.status")
    if status not in SUPPORTED_STATUSES:
        raise MissionRunnerError("unsupported mission status")
    _integer(mission["priority"], "mission.priority")
    _utc(mission["deadline_at"], "mission.deadline_at")
    _sha256(mission["state_digest"], "mission.state_digest")

    queue = _exact(projection["queue"], QUEUE_KEYS, "queue")
    total = _integer(queue["total"], "queue.total", maximum=MAX_QUEUE_TOTAL)
    counts = queue["counts"]
    if not isinstance(counts, Mapping) or len(counts) > 32:
        raise MissionRunnerError("queue.counts must be a bounded mapping")
    normalized_counts: dict[str, int] = {}
    for key, value in counts.items():
        name = _text(key, "queue status")
        if name not in SUPPORTED_STATUSES:
            raise MissionRunnerError("queue contains unsupported task status")
        normalized_counts[name] = _integer(value, f"queue.counts.{name}", maximum=MAX_QUEUE_TOTAL)
    if sum(normalized_counts.values()) != total:
        raise MissionRunnerError("queue counts do not equal queue total")

    _bounded_string_list(projection["agents"], "agents")
    _bounded_string_list(projection["runners"], "runners")
    for field in ("local_node", "data", "providers", "paper"):
        _text(projection[field], field)
    if projection["paper"] != "paper-only":
        raise MissionRunnerError("Mission Control is not paper-only")

    circuits = _exact(projection["circuits"], CIRCUIT_KEYS, "circuits")
    if any(not isinstance(value, bool) for value in circuits.values()):
        raise MissionRunnerError("circuit values must be boolean")
    limits = _exact(projection["limits"], LIMIT_KEYS, "limits")
    if any(not isinstance(value, bool) for value in limits.values()):
        raise MissionRunnerError("limit values must be boolean")
    notifications = projection["notifications"]
    if not isinstance(notifications, list) or len(notifications) > MAX_LIST_ITEMS:
        raise MissionRunnerError("notifications must be a bounded list")
    if any(not isinstance(item, Mapping) for item in notifications):
        raise MissionRunnerError("notifications must contain objects")

    result = dict(projection)
    result["mission"] = mission
    result["queue"] = {"counts": normalized_counts, "total": total}
    result["mission"]["mission_id"] = mission_id
    return result


def _plan_action(status: str, projection: Mapping[str, Any]) -> tuple[str, str]:
    limits = projection["limits"]
    circuits = projection["circuits"]
    if limits["resource_limited"]:
        return "hold", "resource_limit"
    if limits["budget_limited"]:
        return "hold", "budget_limit"
    open_circuits = sorted(name for name, opened in circuits.items() if opened)
    if open_circuits:
        return "hold", f"{open_circuits[0]}_circuit_open"
    if status in ACTIVE_STATUSES:
        return "continue_current_mission", "bounded_read_only_plan"
    if status == "BLOCKED":
        return "hold", "mission_blocked"
    if status == "OWNER_REQUIRED":
        return "hold", "owner_required"
    if status == "PAUSED":
        return "hold", "mission_paused"
    if status in TERMINAL_STATUSES:
        return "no_op", "mission_terminal"
    raise MissionRunnerError("unsupported mission status")


def orchestrate(projection: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_projection(projection)
    mission = validated["mission"]
    queue = validated["queue"]
    status = mission["status"]
    action, reason_code = _plan_action(status, validated)
    selected = mission["mission_id"] if status not in TERMINAL_STATUSES else None
    projection_digest = hashlib.sha256(_canonical(validated)).hexdigest()
    return {
        "contract_version": MISSION_RUNNER_CONTRACT_VERSION,
        "executed": True,
        "state_mutation": False,
        "reversible": True,
        "paper_only": True,
        "orchestration_action": action,
        "reason_code": reason_code,
        "selected_mission_id": selected,
        "selected_mission_title": mission["title"] if selected else None,
        "parallel_mission_ids": [selected] if selected else [],
        "parallel_mission_titles": [mission["title"]] if selected else [],
        "mission_state_digest": mission["state_digest"],
        "projection_digest": projection_digest,
        "queue_digest": projection_digest,
        "ready_count": queue["counts"].get("READY", 0),
        "running_count": queue["counts"].get("RUNNING", 0),
        "blocked_count": queue["counts"].get("BLOCKED", 0),
        "queued_count": queue["counts"].get("PENDING", 0),
        "queue_total": queue["total"],
    }


def run_mission_orchestration(projection: Mapping[str, Any]) -> dict[str, Any]:
    return orchestrate(projection)
