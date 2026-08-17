from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
GENESIS_DIGEST = "0" * 64
ACTIVE_TASK_STATES = {"LEASED", "RUNNING"}
TERMINAL_TASK_STATES = {"DONE", "CANCELLED", "FAILED"}
TRANSIENT_FAILURES = {"network_unavailable", "provider_unavailable", "local_node_offline"}
CIRCUITS = {"provider", "data", "strategy", "risk"}

MISSION_SPEC_KEYS = {
    "schema_version", "mission_id", "idempotency_key", "title", "priority", "authority",
    "deadline_at", "max_parallel_tasks", "tasks",
}
TASK_SPEC_KEYS = {
    "task_id", "idempotency_key", "title", "priority", "dependencies", "authority",
    "owner_group", "timeout_seconds", "max_attempts", "requires_local_node",
    "circuit_requirements",
}
POLICY_KEYS = {
    "schema_version", "max_mission_authority", "max_task_authority", "max_attempts",
    "max_timeout_seconds", "max_parallel_tasks", "max_notifications",
}
ENV_KEYS = {
    "local_node_online", "resource_limited", "budget_limited", "circuits", "owners",
    "agents", "runners", "data_state", "provider_state", "paper_state",
}
COMMAND_KEYS = {"command_id", "action", "task_id", "notification_id"}
RESULT_KEYS = {
    "command_id", "task_id", "lease_id", "owner_id", "outcome", "failure_class",
    "evidence_digest",
}
TASK_STATE_KEYS = TASK_SPEC_KEYS | {
    "status", "assigned_owner", "lease_id", "lease_expires_at", "attempt", "started_at",
    "completed_at", "last_failure_class", "blocked_reason", "dispatch_key",
}
NOTIFICATION_KEYS = {
    "notification_id", "kind", "severity", "task_id", "reason_code", "created_at",
    "acknowledged",
}
STATE_KEYS = {
    "schema_version", "mission_id", "idempotency_key", "title", "priority", "authority",
    "status", "created_at", "updated_at", "deadline_at", "max_parallel_tasks", "tasks",
    "processed_commands", "notifications", "event_sequence", "previous_event_digest",
    "state_digest",
}


class MissionControlError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MissionControlError("value is not canonically serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _exact(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise MissionControlError(f"{name} schema mismatch")
    return dict(value)


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 180:
        raise MissionControlError(f"{field} must be a non-empty bounded string")
    return value


def _integer(value: Any, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MissionControlError(f"{field} must be an integer >= {minimum}")
    return value


def _utc(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise MissionControlError(f"{field} must be UTC ISO-8601")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MissionControlError(f"{field} must be UTC ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise MissionControlError(f"{field} must be UTC")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise MissionControlError(f"{field} must be SHA-256")
    try:
        int(value, 16)
    except ValueError as exc:
        raise MissionControlError(f"{field} must be hexadecimal") from exc
    return value.lower()


def validate_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    policy = _exact(policy, POLICY_KEYS, "mission policy")
    if policy["schema_version"] != SCHEMA_VERSION:
        raise MissionControlError("unsupported mission policy schema")
    for field in ("max_mission_authority", "max_task_authority"):
        level = _integer(policy[field], f"policy.{field}")
        if level > 3:
            raise MissionControlError("mission policy cannot autonomously authorize L4")
    _integer(policy["max_attempts"], "policy.max_attempts", minimum=1)
    _integer(policy["max_timeout_seconds"], "policy.max_timeout_seconds", minimum=1)
    _integer(policy["max_parallel_tasks"], "policy.max_parallel_tasks", minimum=1)
    _integer(policy["max_notifications"], "policy.max_notifications", minimum=1)
    return policy


def _validate_task_spec(task: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    task = _exact(task, TASK_SPEC_KEYS, "task spec")
    for field in ("task_id", "idempotency_key", "title", "owner_group"):
        _id(task[field], f"task.{field}")
    _integer(task["priority"], "task.priority")
    authority = _integer(task["authority"], "task.authority")
    if authority > 4:
        raise MissionControlError("task authority is invalid")
    timeout = _integer(task["timeout_seconds"], "task.timeout_seconds", minimum=1)
    attempts = _integer(task["max_attempts"], "task.max_attempts", minimum=1)
    if timeout > policy["max_timeout_seconds"]:
        raise MissionControlError("task timeout exceeds policy")
    if attempts > policy["max_attempts"]:
        raise MissionControlError("task retry budget exceeds policy")
    if not isinstance(task["requires_local_node"], bool):
        raise MissionControlError("requires_local_node must be boolean")
    if not isinstance(task["dependencies"], list) or any(not isinstance(item, str) or not item for item in task["dependencies"]):
        raise MissionControlError("task dependencies must be a string list")
    if len(task["dependencies"]) != len(set(task["dependencies"])):
        raise MissionControlError("task dependencies contain duplicates")
    if not isinstance(task["circuit_requirements"], list) or not set(task["circuit_requirements"]).issubset(CIRCUITS):
        raise MissionControlError("task circuit requirements are invalid")
    if len(task["circuit_requirements"]) != len(set(task["circuit_requirements"])):
        raise MissionControlError("task circuit requirements contain duplicates")
    return task


def _assert_acyclic(tasks: list[dict[str, Any]]) -> None:
    by_id = {task["task_id"]: task for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise MissionControlError("mission dependency graph contains a cycle")
        visiting.add(task_id)
        for dependency in by_id[task_id]["dependencies"]:
            if dependency not in by_id:
                raise MissionControlError(f"unknown dependency: {dependency}")
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in by_id:
        visit(task_id)


def _state_digest(state: Mapping[str, Any]) -> str:
    return _digest({key: value for key, value in state.items() if key != "state_digest"})


def _seal(state: dict[str, Any], now: str | None = None) -> dict[str, Any]:
    if now is not None:
        state["updated_at"] = now
    state["state_digest"] = _state_digest(state)
    return state


def create_mission(spec: Mapping[str, Any], policy: Mapping[str, Any], *, created_at: str) -> dict[str, Any]:
    policy = validate_policy(policy)
    spec = _exact(spec, MISSION_SPEC_KEYS, "mission spec")
    if spec["schema_version"] != SCHEMA_VERSION:
        raise MissionControlError("unsupported mission spec schema")
    for field in ("mission_id", "idempotency_key", "title"):
        _id(spec[field], f"mission.{field}")
    _integer(spec["priority"], "mission.priority")
    authority = _integer(spec["authority"], "mission.authority")
    if authority > 4:
        raise MissionControlError("mission authority is invalid")
    max_parallel = _integer(spec["max_parallel_tasks"], "mission.max_parallel_tasks", minimum=1)
    if max_parallel > policy["max_parallel_tasks"]:
        raise MissionControlError("mission parallelism exceeds policy")
    created = _utc(created_at, "created_at")
    deadline = _utc(spec["deadline_at"], "mission.deadline_at")
    if deadline <= created:
        raise MissionControlError("mission deadline must be in the future")
    if not isinstance(spec["tasks"], list) or not spec["tasks"]:
        raise MissionControlError("mission requires tasks")
    tasks = [_validate_task_spec(task, policy) for task in spec["tasks"]]
    task_ids = [task["task_id"] for task in tasks]
    idempotency = [task["idempotency_key"] for task in tasks]
    if len(task_ids) != len(set(task_ids)) or len(idempotency) != len(set(idempotency)):
        raise MissionControlError("task IDs and idempotency keys must be unique")
    _assert_acyclic(tasks)

    task_states = []
    for task in tasks:
        task_states.append({
            **deepcopy(task),
            "status": "PENDING",
            "assigned_owner": None,
            "lease_id": None,
            "lease_expires_at": None,
            "attempt": 0,
            "started_at": None,
            "completed_at": None,
            "last_failure_class": None,
            "blocked_reason": "owner_required" if task["authority"] >= 4 else None,
            "dispatch_key": None,
        })
        if task["authority"] >= 4:
            task_states[-1]["status"] = "OWNER_REQUIRED"

    state = {
        "schema_version": SCHEMA_VERSION,
        "mission_id": spec["mission_id"],
        "idempotency_key": spec["idempotency_key"],
        "title": spec["title"],
        "priority": spec["priority"],
        "authority": authority,
        "status": "OWNER_REQUIRED" if authority >= 4 else "PENDING",
        "created_at": _iso(created),
        "updated_at": _iso(created),
        "deadline_at": _iso(deadline),
        "max_parallel_tasks": max_parallel,
        "tasks": task_states,
        "processed_commands": [],
        "notifications": [],
        "event_sequence": 0,
        "previous_event_digest": GENESIS_DIGEST,
        "state_digest": "",
    }
    if authority >= 4:
        _notify(state, "owner_required", "critical", None, "mission_owner_required", _iso(created), policy)
    for task in task_states:
        if task["status"] == "OWNER_REQUIRED":
            _notify(state, "owner_required", "critical", task["task_id"], "task_owner_required", _iso(created), policy)
    return _seal(state)


def validate_state(state: Mapping[str, Any]) -> dict[str, Any]:
    state = _exact(state, STATE_KEYS, "mission state")
    if state["schema_version"] != SCHEMA_VERSION:
        raise MissionControlError("unsupported mission state schema")
    _id(state["mission_id"], "state.mission_id")
    _id(state["idempotency_key"], "state.idempotency_key")
    _utc(state["created_at"], "state.created_at")
    _utc(state["updated_at"], "state.updated_at")
    _utc(state["deadline_at"], "state.deadline_at")
    if not isinstance(state["tasks"], list):
        raise MissionControlError("state.tasks must be a list")
    ids = set()
    for task in state["tasks"]:
        task = _exact(task, TASK_STATE_KEYS, "task state")
        _id(task["task_id"], "task.task_id")
        if task["task_id"] in ids:
            raise MissionControlError("duplicate task state")
        ids.add(task["task_id"])
        if task["status"] not in {"PENDING", "READY", "LEASED", "RUNNING", "BLOCKED", "OWNER_REQUIRED", "DONE", "CANCELLED", "FAILED"}:
            raise MissionControlError("unknown task status")
        _integer(task["attempt"], "task.attempt")
        if task["lease_id"] is not None:
            _id(task["lease_id"], "task.lease_id")
        if task["dispatch_key"] is not None:
            _id(task["dispatch_key"], "task.dispatch_key")
    if not isinstance(state["processed_commands"], list) or len(state["processed_commands"]) != len(set(state["processed_commands"])):
        raise MissionControlError("processed commands are malformed")
    if not isinstance(state["notifications"], list):
        raise MissionControlError("notifications must be a list")
    for notification in state["notifications"]:
        notification = _exact(notification, NOTIFICATION_KEYS, "notification")
        if notification["severity"] not in {"info", "warning", "critical"}:
            raise MissionControlError("invalid notification severity")
    _integer(state["event_sequence"], "state.event_sequence")
    _sha256(state["previous_event_digest"], "state.previous_event_digest")
    if _sha256(state["state_digest"], "state.state_digest") != _state_digest(state):
        raise MissionControlError("mission state digest mismatch")
    return deepcopy(state)


def validate_environment(environment: Mapping[str, Any]) -> dict[str, Any]:
    env = _exact(environment, ENV_KEYS, "mission environment")
    for field in ("local_node_online", "resource_limited", "budget_limited"):
        if not isinstance(env[field], bool):
            raise MissionControlError(f"environment.{field} must be boolean")
    if not isinstance(env["circuits"], Mapping) or set(env["circuits"]) != CIRCUITS:
        raise MissionControlError("environment circuits schema mismatch")
    if any(not isinstance(value, bool) for value in env["circuits"].values()):
        raise MissionControlError("circuit values must be boolean")
    if not isinstance(env["owners"], Mapping):
        raise MissionControlError("owners must be a mapping")
    for group, owners in env["owners"].items():
        _id(group, "owner group")
        if not isinstance(owners, list) or any(not isinstance(owner, str) or not owner for owner in owners):
            raise MissionControlError("owner lists are malformed")
    for field in ("agents", "runners"):
        if not isinstance(env[field], list) or any(not isinstance(item, str) or not item for item in env[field]):
            raise MissionControlError(f"environment.{field} must be a string list")
    for field in ("data_state", "provider_state", "paper_state"):
        _id(env[field], f"environment.{field}")
    return deepcopy(env)


def _notify(
    state: dict[str, Any], kind: str, severity: str, task_id: str | None, reason_code: str,
    now: str, policy: Mapping[str, Any],
) -> None:
    notification_id = "note-" + _digest({
        "mission_id": state["mission_id"], "kind": kind, "task_id": task_id,
        "reason_code": reason_code,
    })[:32]
    if any(item["notification_id"] == notification_id for item in state["notifications"]):
        return
    state["notifications"].append({
        "notification_id": notification_id,
        "kind": kind,
        "severity": severity,
        "task_id": task_id,
        "reason_code": reason_code,
        "created_at": now,
        "acknowledged": False,
    })
    if len(state["notifications"]) > policy["max_notifications"]:
        state["notifications"] = state["notifications"][-policy["max_notifications"]:]


def _event(state: dict[str, Any], kind: str, reason: str, now: str, subject: str | None = None) -> None:
    sequence = state["event_sequence"] + 1
    body = {
        "mission_id": state["mission_id"], "sequence": sequence, "kind": kind,
        "reason": reason, "at": now, "subject": subject,
        "previous": state["previous_event_digest"],
    }
    state["event_sequence"] = sequence
    state["previous_event_digest"] = _digest(body)


def _task_index(state: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {task["task_id"]: task for task in state["tasks"]}


def _deps_done(task: Mapping[str, Any], by_id: Mapping[str, Mapping[str, Any]]) -> bool:
    return all(by_id[dependency]["status"] == "DONE" for dependency in task["dependencies"])


def _blocking_reason(task: Mapping[str, Any], env: Mapping[str, Any]) -> str | None:
    if task["requires_local_node"] and not env["local_node_online"]:
        return "local_node_offline"
    if env["resource_limited"]:
        return "resource_limit"
    if env["budget_limited"]:
        return "budget_limit"
    if env["data_state"] == "stale" and "data" in task["circuit_requirements"]:
        return "stale_data"
    for circuit in task["circuit_requirements"]:
        if env["circuits"][circuit]:
            return f"{circuit}_circuit_open"
    owners = env["owners"].get(task["owner_group"], [])
    if not owners:
        return "owner_unavailable"
    return None


def _block_notification(reason: str) -> tuple[str, str, str]:
    if reason == "stale_data":
        return "stale_data", "critical", reason
    if reason == "budget_limit":
        return "budget_limit", "warning", reason
    if reason == "resource_limit":
        return "resource_limit", "warning", reason
    if reason == "local_node_offline":
        return "block", "warning", reason
    if reason.endswith("_circuit_open"):
        return "block", "critical", reason
    return "block", "warning", reason


def _refresh_mission_status(state: dict[str, Any]) -> None:
    statuses = {task["status"] for task in state["tasks"]}
    if state["status"] in {"CANCELLED", "PAUSED"}:
        return
    if statuses and statuses <= {"DONE"}:
        state["status"] = "DONE"
    elif "OWNER_REQUIRED" in statuses:
        state["status"] = "OWNER_REQUIRED"
    elif "FAILED" in statuses:
        state["status"] = "FAILED"
    elif statuses & {"LEASED", "RUNNING"}:
        state["status"] = "RUNNING"
    elif "BLOCKED" in statuses:
        state["status"] = "BLOCKED"
    elif statuses & {"READY", "PENDING"}:
        state["status"] = "READY"


def schedule(
    state: Mapping[str, Any], environment: Mapping[str, Any], policy: Mapping[str, Any], *, now: str
) -> tuple[dict[str, Any], tuple[dict[str, str], ...]]:
    state = validate_state(state)
    env = validate_environment(environment)
    policy = validate_policy(policy)
    now_dt = _utc(now, "now")
    if state["status"] in {"DONE", "CANCELLED", "FAILED", "OWNER_REQUIRED", "PAUSED"}:
        return state, ()
    if now_dt >= _utc(state["deadline_at"], "state.deadline_at"):
        state["status"] = "FAILED"
        for task in state["tasks"]:
            if task["status"] not in TERMINAL_TASK_STATES:
                task["status"] = "FAILED"
                task["blocked_reason"] = "mission_deadline_exceeded"
        _notify(state, "failure", "critical", None, "mission_deadline_exceeded", now, policy)
        _event(state, "mission_failed", "mission_deadline_exceeded", now)
        return _seal(state, now), ()

    by_id = _task_index(state)
    for task in state["tasks"]:
        if task["status"] == "PENDING" and _deps_done(task, by_id):
            task["status"] = "READY"
            _event(state, "task_ready", "dependencies_satisfied", now, task["task_id"])
        if task["status"] not in {"READY", "BLOCKED"}:
            continue
        if task["authority"] >= 4 or task["authority"] > policy["max_task_authority"]:
            task["status"] = "OWNER_REQUIRED"
            task["blocked_reason"] = "task_owner_required"
            _notify(state, "owner_required", "critical", task["task_id"], "task_owner_required", now, policy)
            _event(state, "task_owner_required", "authority_boundary", now, task["task_id"])
            continue
        reason = _blocking_reason(task, env)
        if reason:
            if task["status"] != "BLOCKED" or task["blocked_reason"] != reason:
                task["status"] = "BLOCKED"
                task["blocked_reason"] = reason
                kind, severity, reason_code = _block_notification(reason)
                _notify(state, kind, severity, task["task_id"], reason_code, now, policy)
                _event(state, "task_blocked", reason, now, task["task_id"])
            continue
        if task["status"] == "BLOCKED":
            task["status"] = "READY"
            previous = task["blocked_reason"] or "blocked"
            task["blocked_reason"] = None
            _notify(state, "recovery", "info", task["task_id"], f"recovered_from_{previous}", now, policy)
            _event(state, "task_recovered", previous, now, task["task_id"])

    active = sum(task["status"] in ACTIVE_TASK_STATES for task in state["tasks"])
    limit = min(state["max_parallel_tasks"], policy["max_parallel_tasks"])
    leases: list[dict[str, str]] = []
    ready = sorted(
        (task for task in state["tasks"] if task["status"] == "READY"),
        key=lambda task: (-task["priority"], task["task_id"]),
    )
    for task in ready:
        if active >= limit:
            break
        owners = sorted(set(env["owners"].get(task["owner_group"], [])))
        if not owners:
            continue
        owner = owners[0]
        attempt = task["attempt"] + 1
        if attempt > min(task["max_attempts"], policy["max_attempts"]):
            task["status"] = "FAILED"
            task["blocked_reason"] = "retry_exhausted"
            _notify(state, "failure", "critical", task["task_id"], "retry_exhausted", now, policy)
            _event(state, "task_failed", "retry_exhausted", now, task["task_id"])
            continue
        lease_id = "lease-" + _digest({
            "mission": state["mission_id"], "task": task["task_id"], "attempt": attempt,
            "owner": owner, "now": now,
        })[:32]
        dispatch_key = "dispatch-" + _digest({
            "mission": state["mission_id"], "task": task["task_id"], "attempt": attempt,
        })[:32]
        task["status"] = "LEASED"
        task["assigned_owner"] = owner
        task["lease_id"] = lease_id
        task["attempt"] = attempt
        task["started_at"] = now
        timeout = min(task["timeout_seconds"], policy["max_timeout_seconds"])
        task["lease_expires_at"] = _iso(now_dt + timedelta(seconds=timeout))
        task["completed_at"] = None
        task["last_failure_class"] = None
        task["blocked_reason"] = None
        task["dispatch_key"] = dispatch_key
        leases.append({
            "mission_id": state["mission_id"], "task_id": task["task_id"], "lease_id": lease_id,
            "owner_id": owner, "dispatch_key": dispatch_key,
        })
        active += 1
        _event(state, "task_leased", "scheduler", now, task["task_id"])
    _refresh_mission_status(state)
    return _seal(state, now), tuple(leases)


def mark_running(
    state: Mapping[str, Any], *, task_id: str, lease_id: str, owner_id: str, now: str
) -> dict[str, Any]:
    state = validate_state(state)
    _utc(now, "now")
    task = _task_index(state).get(task_id)
    if task is None:
        raise MissionControlError("unknown task")
    if task["status"] != "LEASED" or task["lease_id"] != lease_id or task["assigned_owner"] != owner_id:
        raise MissionControlError("lease ownership mismatch")
    task["status"] = "RUNNING"
    _event(state, "task_running", "lease_started", now, task_id)
    _refresh_mission_status(state)
    return _seal(state, now)


def record_result(
    state: Mapping[str, Any], result: Mapping[str, Any], policy: Mapping[str, Any], *, now: str
) -> dict[str, Any]:
    state = validate_state(state)
    policy = validate_policy(policy)
    result = _exact(result, RESULT_KEYS, "task result")
    _utc(now, "now")
    command_id = _id(result["command_id"], "result.command_id")
    if command_id in state["processed_commands"]:
        return state
    task = _task_index(state).get(_id(result["task_id"], "result.task_id"))
    if task is None:
        raise MissionControlError("unknown task")
    if task["status"] not in ACTIVE_TASK_STATES:
        raise MissionControlError("task is not active")
    if result["lease_id"] != task["lease_id"] or result["owner_id"] != task["assigned_owner"]:
        raise MissionControlError("result lease ownership mismatch")
    _sha256(result["evidence_digest"], "result.evidence_digest")
    if result["outcome"] not in {"success", "failure"}:
        raise MissionControlError("unsupported result outcome")
    if result["failure_class"] is not None:
        _id(result["failure_class"], "result.failure_class")
    state["processed_commands"].append(command_id)
    task["completed_at"] = now
    task["lease_expires_at"] = None
    task["lease_id"] = None
    task["assigned_owner"] = None

    if result["outcome"] == "success":
        task["status"] = "DONE"
        task["blocked_reason"] = None
        task["last_failure_class"] = None
        _event(state, "task_done", "success", now, task["task_id"])
    else:
        failure = result["failure_class"] or "persistent"
        task["last_failure_class"] = failure
        if failure in TRANSIENT_FAILURES and task["attempt"] < min(task["max_attempts"], policy["max_attempts"]):
            task["status"] = "READY"
            task["blocked_reason"] = None
            _notify(state, "recovery", "warning", task["task_id"], f"retry_{failure}", now, policy)
            _event(state, "task_retry_ready", failure, now, task["task_id"])
        else:
            task["status"] = "BLOCKED" if failure not in {"corrupt_state", "policy_denied"} else "FAILED"
            task["blocked_reason"] = "root_cause_required" if task["status"] == "BLOCKED" else failure
            _notify(state, "failure", "critical", task["task_id"], failure, now, policy)
            _event(state, "task_failure", failure, now, task["task_id"])
    task["dispatch_key"] = None
    _refresh_mission_status(state)
    return _seal(state, now)


def reconcile_restart(
    state: Mapping[str, Any], environment: Mapping[str, Any], policy: Mapping[str, Any], *, now: str
) -> dict[str, Any]:
    state = validate_state(state)
    env = validate_environment(environment)
    policy = validate_policy(policy)
    now_dt = _utc(now, "now")
    for task in state["tasks"]:
        if task["status"] in ACTIVE_TASK_STATES and task["lease_expires_at"]:
            expiry = _utc(task["lease_expires_at"], "task.lease_expires_at")
            if expiry <= now_dt:
                task["assigned_owner"] = None
                task["lease_id"] = None
                task["lease_expires_at"] = None
                task["dispatch_key"] = None
                if task["attempt"] < min(task["max_attempts"], policy["max_attempts"]):
                    task["status"] = "READY"
                    task["last_failure_class"] = "restart_recovery"
                    _notify(state, "recovery", "warning", task["task_id"], "lease_expired_recovered", now, policy)
                    _event(state, "task_recovered", "expired_lease", now, task["task_id"])
                else:
                    task["status"] = "FAILED"
                    task["blocked_reason"] = "retry_exhausted"
                    _notify(state, "failure", "critical", task["task_id"], "retry_exhausted", now, policy)
                    _event(state, "task_failed", "retry_exhausted", now, task["task_id"])
        elif task["status"] == "BLOCKED" and task["blocked_reason"] in {
            "local_node_offline", "resource_limit", "budget_limit", "stale_data",
            "provider_circuit_open", "data_circuit_open", "strategy_circuit_open", "risk_circuit_open",
            "owner_unavailable",
        }:
            reason = _blocking_reason(task, env)
            if reason is None:
                task["status"] = "READY"
                previous = task["blocked_reason"]
                task["blocked_reason"] = None
                _notify(state, "recovery", "info", task["task_id"], f"recovered_from_{previous}", now, policy)
                _event(state, "task_recovered", previous, now, task["task_id"])
    _refresh_mission_status(state)
    return _seal(state, now)


def apply_command(
    state: Mapping[str, Any], command: Mapping[str, Any], policy: Mapping[str, Any], *, now: str
) -> dict[str, Any]:
    state = validate_state(state)
    policy = validate_policy(policy)
    command = _exact(command, COMMAND_KEYS, "mission command")
    _utc(now, "now")
    command_id = _id(command["command_id"], "command.command_id")
    if command_id in state["processed_commands"]:
        return state
    action = command["action"]
    if action not in {"pause_mission", "resume_mission", "cancel_mission", "cancel_task", "ack_notification"}:
        raise MissionControlError("unsupported mission command")
    state["processed_commands"].append(command_id)

    if action == "pause_mission":
        if state["status"] not in {"DONE", "CANCELLED", "FAILED"}:
            state["status"] = "PAUSED"
            _event(state, "mission_paused", "operator_command", now)
    elif action == "resume_mission":
        if state["status"] == "PAUSED":
            state["status"] = "READY"
            _event(state, "mission_resumed", "operator_command", now)
    elif action == "cancel_mission":
        if state["status"] != "DONE":
            state["status"] = "CANCELLED"
            for task in state["tasks"]:
                if task["status"] not in TERMINAL_TASK_STATES:
                    task["status"] = "CANCELLED"
                    task["assigned_owner"] = None
                    task["lease_id"] = None
                    task["lease_expires_at"] = None
                    task["dispatch_key"] = None
                    task["completed_at"] = now
            _event(state, "mission_cancelled", "operator_command", now)
    elif action == "cancel_task":
        task_id = _id(command["task_id"], "command.task_id")
        task = _task_index(state).get(task_id)
        if task is None:
            raise MissionControlError("unknown task")
        if task["status"] not in TERMINAL_TASK_STATES:
            task["status"] = "CANCELLED"
            task["assigned_owner"] = None
            task["lease_id"] = None
            task["lease_expires_at"] = None
            task["dispatch_key"] = None
            task["completed_at"] = now
            _event(state, "task_cancelled", "operator_command", now, task_id)
        _refresh_mission_status(state)
    elif action == "ack_notification":
        notification_id = _id(command["notification_id"], "command.notification_id")
        found = False
        for item in state["notifications"]:
            if item["notification_id"] == notification_id:
                item["acknowledged"] = True
                found = True
                break
        if not found:
            raise MissionControlError("unknown notification")
        _event(state, "notification_acknowledged", "operator_command", now, notification_id)
    return _seal(state, now)


def mission_control_projection(state: Mapping[str, Any], environment: Mapping[str, Any]) -> dict[str, Any]:
    state = validate_state(state)
    env = validate_environment(environment)
    counts: dict[str, int] = {}
    for task in state["tasks"]:
        counts[task["status"]] = counts.get(task["status"], 0) + 1
    active_notifications = [item for item in state["notifications"] if not item["acknowledged"]]
    return {
        "contract_version": "nexus.mission-control.read.v1",
        "mission": {
            "mission_id": state["mission_id"], "title": state["title"], "status": state["status"],
            "priority": state["priority"], "deadline_at": state["deadline_at"],
            "state_digest": state["state_digest"],
        },
        "queue": {"counts": counts, "total": len(state["tasks"])},
        "agents": list(env["agents"]),
        "runners": list(env["runners"]),
        "local_node": "online" if env["local_node_online"] else "offline",
        "data": env["data_state"],
        "providers": env["provider_state"],
        "paper": env["paper_state"],
        "circuits": dict(env["circuits"]),
        "limits": {"resource_limited": env["resource_limited"], "budget_limited": env["budget_limited"]},
        "notifications": deepcopy(active_notifications),
    }


def save_state(path: str | Path, state: Mapping[str, Any]) -> None:
    state = validate_state(state)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(state, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        raise MissionControlError("durable mission state commit failed") from exc


def load_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MissionControlError("durable mission state is missing or corrupt") from exc
    return validate_state(payload)


def save_projection(path: str | Path, projection: Mapping[str, Any]) -> None:
    if not isinstance(projection, Mapping) or projection.get("contract_version") != "nexus.mission-control.read.v1":
        raise MissionControlError("mission projection contract mismatch")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(dict(projection), sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    except OSError as exc:
        raise MissionControlError("mission projection commit failed") from exc
