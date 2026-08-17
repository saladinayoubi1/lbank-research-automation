from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

MISSION_SCHEMA = "nexus.phase5-mission.v1"
RUNTIME_SCHEMA = "nexus.phase5-runtime.v1"

# Fields that define authorization/acceptance semantics for a task. Phase, gate,
# title, priority and preferred resources are intentionally metadata/scheduling
# hints and do not define task authority identity.
TASK_SPEC_FIELDS = (
    "id",
    "dependencies",
    "required_capabilities",
    "authority",
    "acceptance",
)

RUNTIME_FIELDS = {
    "status",
    "ready_at",
    "assigned_worker",
    "producer",
    "verifier",
    "lease_id",
    "leased_at",
    "heartbeat_at",
    "lease_expires_at",
    "attempt",
    "transient_retries",
    "triage_reason",
    "triage_started_at",
    "triage_mode",
    "required_output",
    "failure_class",
    "failure_evidence",
    "result_evidence",
    "verification_evidence",
    "verified_at",
    "blocked_reason",
    "dispatch_id",
    "dispatch_transport",
    "dispatched_at",
    "result_artifact_ingested",
    "result_received_at",
    "correlation_id",
}


class MissionContractError(ValueError):
    pass


class RuntimeStateError(RuntimeError):
    pass


def _bounded_string(value: Any, field: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise MissionContractError(f"{field} must be a non-empty bounded string")
    return value


def _canonical_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _policy_version(config: dict[str, Any]) -> str:
    policy = config.get("policy")
    if not isinstance(policy, dict):
        raise MissionContractError("policy must be an object")
    return _bounded_string(policy.get("version"), "policy.version")


def task_spec_payload(config: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    return {
        "mission_schema": MISSION_SCHEMA,
        "mission_id": _bounded_string(config.get("mission_id"), "mission_id"),
        "mission_revision": config.get("mission_revision"),
        "policy_version": _policy_version(config),
        **{field: deepcopy(task.get(field)) for field in TASK_SPEC_FIELDS},
    }


def task_spec_digest(config: dict[str, Any], task: dict[str, Any]) -> str:
    return _canonical_digest(task_spec_payload(config, task))


def _validate_dag(tasks: list[dict[str, Any]]) -> None:
    by_id = {task["id"]: task for task in tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            raise MissionContractError(f"task dependency cycle detected at {task_id}")
        visiting.add(task_id)
        for dep in by_id[task_id].get("dependencies", []):
            visit(dep)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in sorted(by_id):
        visit(task_id)


def validate_and_materialize(config: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise MissionContractError("mission config root must be an object")
    if config.get("schema_version") != MISSION_SCHEMA:
        raise MissionContractError("unsupported Phase 5 mission schema")

    mission_id = _bounded_string(config.get("mission_id"), "mission_id")
    revision = config.get("mission_revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise MissionContractError("mission_revision must be a positive integer")
    policy_version = _policy_version(config)

    phase = config.get("phase")
    if phase is not None and (isinstance(phase, bool) or not isinstance(phase, int) or phase < 1):
        raise MissionContractError("phase metadata must be a positive integer")

    workers = config.get("workers")
    tasks = config.get("tasks")
    if not isinstance(workers, list) or not isinstance(tasks, list):
        raise MissionContractError("workers/tasks must be lists")

    worker_ids: set[str] = set()
    for worker in workers:
        if not isinstance(worker, dict):
            raise MissionContractError("worker entries must be objects")
        worker_id = _bounded_string(worker.get("id"), "worker.id")
        if worker_id in worker_ids:
            raise MissionContractError("worker ids must be unique")
        worker_ids.add(worker_id)

    task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise MissionContractError("task entries must be objects")
        task_id = _bounded_string(task.get("id"), "task.id")
        if task_id in task_ids:
            raise MissionContractError("task ids must be unique")
        task_ids.add(task_id)

    for task in tasks:
        deps = task.get("dependencies", [])
        if not isinstance(deps, list) or any(not isinstance(dep, str) or not dep for dep in deps):
            raise MissionContractError(f"dependencies must be task-id strings for {task['id']}")
        if len(deps) != len(set(deps)):
            raise MissionContractError(f"duplicate dependencies for {task['id']}")
        unknown = set(deps) - task_ids
        if unknown:
            raise MissionContractError(f"unknown dependencies for {task['id']}: {sorted(unknown)}")
        if task["id"] in deps:
            raise MissionContractError(f"self dependency for {task['id']}")

        authority = task.get("authority")
        if isinstance(authority, bool) or not isinstance(authority, int) or authority not in range(0, 5):
            raise MissionContractError(f"invalid authority for {task['id']}")

        required = task.get("required_capabilities", [])
        acceptance = task.get("acceptance", [])
        if not isinstance(required, list) or any(not isinstance(item, str) or not item for item in required):
            raise MissionContractError(f"invalid required_capabilities for {task['id']}")
        if not isinstance(acceptance, list) or not acceptance or any(not isinstance(item, str) or not item for item in acceptance):
            raise MissionContractError(f"invalid acceptance for {task['id']}")

    _validate_dag(tasks)

    materialized = deepcopy(config)
    for task in materialized["tasks"]:
        task["mission_id"] = mission_id
        task["mission_revision"] = revision
        task["policy_version"] = policy_version
        task["spec_digest"] = task_spec_digest(config, task)
    return materialized


def to_agent_manager_config(config: dict[str, Any]) -> dict[str, Any]:
    mission = validate_and_materialize(config)
    policy = deepcopy(mission["policy"])
    policy.pop("version", None)
    return {
        "schema_version": 1,
        "phase": mission.get("phase", 5),
        "phase5_runtime_schema": RUNTIME_SCHEMA,
        "mission_id": mission["mission_id"],
        "mission_revision": mission["mission_revision"],
        "policy_version": mission["policy"]["version"],
        "policy": policy,
        "workers": deepcopy(mission["workers"]),
        "tasks": deepcopy(mission["tasks"]),
    }


def merge_compatible_runtime(template: dict[str, Any], runtime: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(template)
    if runtime is None:
        return merged
    if not isinstance(runtime, dict) or runtime.get("phase5_runtime_schema") != RUNTIME_SCHEMA:
        raise RuntimeStateError("runtime state schema is missing or unsupported")
    if runtime.get("mission_id") != template.get("mission_id"):
        raise RuntimeStateError("runtime state belongs to a different mission")

    old_by_id = {
        task["id"]: task
        for task in runtime.get("tasks", [])
        if isinstance(task, dict) and isinstance(task.get("id"), str)
    }
    new_ids = {task["id"] for task in merged["tasks"]}

    for task in merged["tasks"]:
        old = old_by_id.get(task["id"])
        if not old:
            continue
        # Runtime is inherited only for the exact authorization/acceptance spec.
        # Phase/gate/title/priority changes do not affect this digest.
        if old.get("spec_digest") != task.get("spec_digest"):
            continue
        for field in RUNTIME_FIELDS:
            if field in old:
                task[field] = deepcopy(old[field])

    for old_id, old in old_by_id.items():
        if old_id in new_ids:
            continue
        historical = deepcopy(old)
        historical["status"] = "QUARANTINED"
        historical["blocked_reason"] = "task removed from current Phase 5 mission definition"
        merged["tasks"].append(historical)

    return merged


def load_runtime_strict(path) -> dict[str, Any] | None:  # Path-like kept generic for tests.
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeStateError("runtime state JSON is corrupt") from exc
    if not isinstance(payload, dict):
        raise RuntimeStateError("runtime state root must be an object")
    if payload.get("phase5_runtime_schema") != RUNTIME_SCHEMA:
        raise RuntimeStateError("runtime state schema is missing or unsupported")
    return payload
