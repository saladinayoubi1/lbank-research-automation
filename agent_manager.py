from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

QUEUE_PATH = Path("config/nexus-agent-manager.json")
STATE_PATH = Path("data/agent_coordination/manager_state.json")
EVENT_PATH = Path("data/agent_coordination/manager_events.jsonl")
DEFAULT_LEASE_MINUTES = 5
TERMINAL = {"DONE", "OWNER_REQUIRED", "QUARANTINED"}
ACTIVE = {"LEASED", "RUNNING", "VERIFYING"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None = None) -> str:
    return (dt or utcnow()).isoformat()


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def emit(kind: str, **fields: Any) -> None:
    EVENT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with EVENT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": iso(), "kind": kind, **fields}, ensure_ascii=False) + "\n")


@dataclass(frozen=True)
class Worker:
    id: str
    capabilities: frozenset[str]
    resources: frozenset[str]
    authority_max: int
    enabled: bool = True
    verifier: bool = False


def load_config(path: Path = QUEUE_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported agent-manager schema")
    return data


def validate_config(config: dict[str, Any]) -> None:
    workers = config.get("workers")
    tasks = config.get("tasks")
    if not isinstance(workers, list) or not isinstance(tasks, list):
        raise ValueError("workers/tasks must be lists")
    worker_ids = {w.get("id") for w in workers}
    task_ids = {t.get("id") for t in tasks}
    if None in worker_ids or len(worker_ids) != len(workers):
        raise ValueError("worker ids must be unique")
    if None in task_ids or len(task_ids) != len(tasks):
        raise ValueError("task ids must be unique")
    for task in tasks:
        deps = task.get("dependencies", [])
        unknown = set(deps) - task_ids
        if unknown:
            raise ValueError(f"unknown dependencies for {task['id']}: {sorted(unknown)}")
        if task.get("authority", 0) not in range(0, 5):
            raise ValueError(f"invalid authority for {task['id']}")
        if task.get("producer") and task["producer"] not in worker_ids:
            raise ValueError(f"unknown producer for {task['id']}")


def workers_from(config: dict[str, Any]) -> list[Worker]:
    return [
        Worker(
            id=w["id"],
            capabilities=frozenset(w.get("capabilities", [])),
            resources=frozenset(w.get("resources", [])),
            authority_max=int(w.get("authority_max", 0)),
            enabled=bool(w.get("enabled", True)),
            verifier=bool(w.get("verifier", False)),
        )
        for w in config["workers"]
    ]


def task_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in config["tasks"]}


def dependencies_done(task: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    return all(by_id[d].get("status") == "DONE" for d in task.get("dependencies", []))


def enforce_owner_boundaries(config: dict[str, Any]) -> None:
    """Fail closed for L4 tasks regardless of restored runtime status.

    Persisted state must never turn an owner-only action into an executable lease,
    verification, triage job, or completed autonomous task.
    """
    for task in config["tasks"]:
        if int(task.get("authority", 0)) < 4 or task.get("status") == "QUARANTINED":
            continue
        prior = task.get("status")
        task["status"] = "OWNER_REQUIRED"
        task["blocked_reason"] = "L4 owner approval required"
        task["assigned_worker"] = None
        task["lease_id"] = None
        task["leased_at"] = None
        task["heartbeat_at"] = None
        task["lease_expires_at"] = None
        if prior != "OWNER_REQUIRED":
            emit("owner_boundary_enforced", task_id=task["id"], prior_status=prior)


def eligible_workers(task: dict[str, Any], workers: list[Worker], *, verifier_only: bool = False) -> list[Worker]:
    needed = set(task.get("required_capabilities", []))
    preferred = set(task.get("preferred_resources", []))
    producer = task.get("producer")
    result: list[tuple[int, str, Worker]] = []
    for worker in workers:
        if not worker.enabled or worker.authority_max < int(task.get("authority", 0)):
            continue
        if verifier_only and not worker.verifier:
            continue
        if verifier_only and producer and worker.id == producer:
            continue
        if not needed.issubset(worker.capabilities):
            continue
        resource_score = len(preferred.intersection(worker.resources))
        result.append((-resource_score, worker.id, worker))
    return [item[2] for item in sorted(result)]


def release_ready_tasks(config: dict[str, Any]) -> None:
    by_id = task_index(config)
    for task in config["tasks"]:
        if task.get("status") == "PENDING" and dependencies_done(task, by_id):
            task["status"] = "READY"
            task["ready_at"] = iso()
            emit("task_ready", task_id=task["id"])


def expire_stale_leases(config: dict[str, Any], now: datetime) -> None:
    for task in config["tasks"]:
        if task.get("status") not in ACTIVE:
            continue
        expiry = parse_time(task.get("lease_expires_at"))
        heartbeat = parse_time(task.get("heartbeat_at"))
        stale = bool(expiry and expiry <= now)
        if heartbeat and heartbeat + timedelta(minutes=DEFAULT_LEASE_MINUTES) <= now:
            stale = True
        if not stale:
            continue
        prior = task.get("assigned_worker")
        task["status"] = "TRIAGE"
        task["triage_reason"] = "stale_lease_or_heartbeat"
        task["triage_started_at"] = iso(now)
        task["assigned_worker"] = None
        task["lease_expires_at"] = None
        task["heartbeat_at"] = None
        emit("five_minute_triage", task_id=task["id"], prior_worker=prior)


def assign_ready_tasks(config: dict[str, Any], now: datetime) -> None:
    workers = workers_from(config)
    busy = {t.get("assigned_worker") for t in config["tasks"] if t.get("status") in ACTIVE}
    max_parallel = int(config.get("policy", {}).get("max_parallel_tasks", 4))
    active_count = sum(t.get("status") in ACTIVE for t in config["tasks"])
    if active_count >= max_parallel:
        return
    ranked = sorted(
        (t for t in config["tasks"] if t.get("status") == "READY"),
        key=lambda t: (-int(t.get("priority", 0)), t["id"]),
    )
    for task in ranked:
        if active_count >= max_parallel:
            break
        if int(task.get("authority", 0)) >= 4:
            task["status"] = "OWNER_REQUIRED"
            task["blocked_reason"] = "L4 owner approval required"
            emit("owner_required", task_id=task["id"])
            continue
        candidates = [w for w in eligible_workers(task, workers) if w.id not in busy]
        if not candidates:
            continue
        worker = candidates[0]
        task["assigned_worker"] = worker.id
        task["producer"] = worker.id
        task["status"] = "LEASED"
        task["lease_id"] = str(uuid.uuid4())
        task["leased_at"] = iso(now)
        task["heartbeat_at"] = iso(now)
        task["lease_expires_at"] = iso(now + timedelta(minutes=DEFAULT_LEASE_MINUTES))
        task["attempt"] = int(task.get("attempt", 0)) + 1
        busy.add(worker.id)
        active_count += 1
        emit("task_leased", task_id=task["id"], worker=worker.id, attempt=task["attempt"])


def route_triage(config: dict[str, Any], now: datetime) -> None:
    workers = workers_from(config)
    for task in config["tasks"]:
        if task.get("status") != "TRIAGE":
            continue
        if int(task.get("authority", 0)) >= 4:
            task["status"] = "OWNER_REQUIRED"
            task["blocked_reason"] = "L4 owner approval required"
            task["assigned_worker"] = None
            emit("owner_boundary_enforced", task_id=task["id"], prior_status="TRIAGE")
            continue
        failure_class = task.get("failure_class", "unknown")
        # Only proven transient failures may be directly retried. Everything else gets RCA first.
        if failure_class in {"startup_failure", "timed_out", "transient_network"} and int(task.get("transient_retries", 0)) < 1:
            task["transient_retries"] = int(task.get("transient_retries", 0)) + 1
            task["status"] = "READY"
            task["ready_at"] = iso(now)
            emit("bounded_transient_retry", task_id=task["id"])
            continue
        rca_caps = {"root_cause_analysis", "diagnostics"}
        candidates = [w for w in workers if w.enabled and rca_caps.issubset(w.capabilities) and w.id != task.get("producer")]
        if not candidates:
            task["status"] = "BLOCKED"
            task["blocked_reason"] = "independent root-cause analyst unavailable"
            emit("triage_blocked", task_id=task["id"])
            continue
        analyst = sorted(candidates, key=lambda w: w.id)[0]
        task["status"] = "RUNNING"
        task["assigned_worker"] = analyst.id
        task["triage_mode"] = "root_cause_first"
        task["required_output"] = ["root_cause", "evidence", "single_best_remediation", "regression_test_plan"]
        task["lease_id"] = str(uuid.uuid4())
        task["heartbeat_at"] = iso(now)
        task["lease_expires_at"] = iso(now + timedelta(minutes=DEFAULT_LEASE_MINUTES))
        emit("root_cause_assigned", task_id=task["id"], worker=analyst.id)


def request_verification(config: dict[str, Any], task: dict[str, Any], now: datetime) -> bool:
    if int(task.get("authority", 0)) >= 4:
        task["status"] = "OWNER_REQUIRED"
        task["blocked_reason"] = "L4 owner approval required"
        task["assigned_worker"] = None
        return False
    workers = workers_from(config)
    candidates = eligible_workers(task, workers, verifier_only=True)
    if not candidates:
        task["status"] = "BLOCKED"
        task["blocked_reason"] = "independent verifier unavailable"
        return False
    verifier = candidates[0]
    task["status"] = "VERIFYING"
    task["assigned_worker"] = verifier.id
    task["verifier"] = verifier.id
    task["lease_id"] = str(uuid.uuid4())
    task["heartbeat_at"] = iso(now)
    task["lease_expires_at"] = iso(now + timedelta(minutes=DEFAULT_LEASE_MINUTES))
    emit("verification_assigned", task_id=task["id"], verifier=verifier.id, producer=task.get("producer"))
    return True


def record_result(config: dict[str, Any], task_id: str, worker_id: str, outcome: str, evidence: dict[str, Any] | None = None) -> None:
    task = task_index(config)[task_id]
    if int(task.get("authority", 0)) >= 4:
        raise ValueError("L4 task results require owner-controlled handling")
    if task.get("assigned_worker") != worker_id:
        raise ValueError("worker does not own current lease")
    evidence = evidence or {}
    if outcome == "success":
        if task.get("status") == "VERIFYING":
            task["status"] = "DONE"
            task["verified_at"] = iso()
            task["verification_evidence"] = evidence
            emit("task_done", task_id=task_id, verifier=worker_id)
        else:
            task["result_evidence"] = evidence
            request_verification(config, task, utcnow())
    elif outcome == "failure":
        task["failure_class"] = evidence.get("failure_class", "deterministic_or_unknown")
        task["failure_evidence"] = evidence
        task["status"] = "TRIAGE"
        task["triage_started_at"] = iso()
        emit("task_failed_to_triage", task_id=task_id, worker=worker_id, failure_class=task["failure_class"])
    else:
        raise ValueError("outcome must be success or failure")


def summarize(config: dict[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for task in config["tasks"]:
        counts[task.get("status", "UNKNOWN")] = counts.get(task.get("status", "UNKNOWN"), 0) + 1
    total = len(config["tasks"])
    done = counts.get("DONE", 0)
    return {
        "generated_at": iso(),
        "phase": config.get("phase"),
        "counts": counts,
        "verified_progress_percent": round((done / total * 100.0) if total else 0.0, 2),
        "owner_required": [t["id"] for t in config["tasks"] if t.get("status") == "OWNER_REQUIRED"],
    }


def cycle(config: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    validate_config(config)
    now = now or utcnow()
    enforce_owner_boundaries(config)
    expire_stale_leases(config, now)
    route_triage(config, now)
    release_ready_tasks(config)
    assign_ready_tasks(config, now)
    return summarize(config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Persistent NEXUS agent manager")
    parser.add_argument("--config", default=str(QUEUE_PATH))
    parser.add_argument("--state", default=str(STATE_PATH))
    args = parser.parse_args()
    path = Path(args.config)
    config = load_config(path)
    summary = cycle(config)
    atomic_json(path, config)
    atomic_json(Path(args.state), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
