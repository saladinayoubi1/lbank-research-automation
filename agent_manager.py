from __future__ import annotations

import argparse
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from nexus_research_missions import PREDECESSOR, TASKS, ANCESTRY, validate_ancestry

QUEUE_PATH = Path("config/nexus-agent-manager.json")
STATE_PATH = Path("data/agent_coordination/manager_state.json")
EVENT_PATH = Path("data/agent_coordination/manager_events.jsonl")
DEFAULT_LEASE_MINUTES = 5
TERMINAL = {"DONE", "OWNER_REQUIRED", "QUARANTINED"}
WAITING_EXTERNAL = "WAITING_EXTERNAL"
ACTIVE = {"LEASED", "RUNNING", "VERIFYING"}
RESEARCH_RCA_BLOCK_REASON = "numerical Research RCA requires reviewed source-bound recovery"


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
    max_concurrent_tasks: int = 1
    available: bool = True
    health_score: float = 1.0
    latency_ms: float = 0.0
    failure_rate: float = 0.0
    cost_units: float = 0.0
    data_locality: frozenset[str] = frozenset()
    trust_domains: frozenset[str] = frozenset()


def load_config(path: Path = QUEUE_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("unsupported agent-manager schema")
    return data


def _bounded_metric(value: Any, field: str, *, minimum: float = 0.0, maximum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    metric = float(value)
    if metric < minimum or (maximum is not None and metric > maximum):
        raise ValueError(f"{field} outside allowed range")
    return metric


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
    for worker in workers:
        capacity = worker.get("max_concurrent_tasks", 1)
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError(f"invalid worker capacity for {worker.get('id')}")
        routing = worker.get("routing", {})
        if not isinstance(routing, dict):
            raise ValueError(f"routing must be an object for {worker.get('id')}")
        _bounded_metric(routing.get("health_score", 1.0), "health_score", maximum=1.0)
        _bounded_metric(routing.get("latency_ms", 0.0), "latency_ms")
        _bounded_metric(routing.get("failure_rate", 0.0), "failure_rate", maximum=1.0)
        _bounded_metric(routing.get("cost_units", 0.0), "cost_units")
        for key in ("data_locality", "trust_domains"):
            value = routing.get(key, [])
            if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
                raise ValueError(f"{key} must be a string list for {worker.get('id')}")
    resource_metrics = config.get("resource_metrics", {})
    if not isinstance(resource_metrics, dict):
        raise ValueError("resource_metrics must be an object")
    for worker_id, metrics in resource_metrics.items():
        if worker_id not in worker_ids or not isinstance(metrics, dict):
            raise ValueError("resource_metrics contains unknown worker or non-object metrics")
        if "available" in metrics and not isinstance(metrics["available"], bool):
            raise ValueError("resource metric available must be boolean")
        _bounded_metric(metrics.get("health_score", 1.0), "health_score", maximum=1.0)
        _bounded_metric(metrics.get("latency_ms", 0.0), "latency_ms")
        _bounded_metric(metrics.get("failure_rate", 0.0), "failure_rate", maximum=1.0)
        _bounded_metric(metrics.get("cost_units", 0.0), "cost_units")
    for task in tasks:
        deps = task.get("dependencies", [])
        unknown = set(deps) - task_ids
        if unknown:
            raise ValueError(f"unknown dependencies for {task['id']}: {sorted(unknown)}")
        if task.get("authority", 0) not in range(0, 5):
            raise ValueError(f"invalid authority for {task['id']}")
        if task.get("producer") and task["producer"] not in worker_ids:
            raise ValueError(f"unknown producer for {task['id']}")
        phase = task.get("phase", config.get("phase"))
        if isinstance(phase, bool) or not isinstance(phase, int) or phase < 1:
            raise ValueError(f"invalid phase for {task['id']}")
        if "max_cost_units" in task:
            _bounded_metric(task["max_cost_units"], "max_cost_units")
        if "min_health_score" in task:
            _bounded_metric(task["min_health_score"], "min_health_score", maximum=1.0)
        if task.get("qa_verifier_only") is True:
            required_verifier = task.get("required_verifier")
            if required_verifier not in worker_ids:
                raise ValueError(f"unknown required verifier for {task['id']}")
            verifier_rows = [row for row in workers if row.get("id") == required_verifier]
            if len(verifier_rows) != 1 or verifier_rows[0].get("verifier") is not True:
                raise ValueError(f"required verifier is not verifier-capable for {task['id']}")
            if not isinstance(task.get("qa_dispatch_enabled"), bool):
                raise ValueError(f"qa_dispatch_enabled must be boolean for {task['id']}")
            handoff = task.get("qa_handoff_task")
            if (
                not isinstance(handoff, dict)
                or handoff.get("required_verifier") != required_verifier
                or handoff.get("task_kind") != "strategy_review_independent_qa"
                or handoff.get("system_map_node") != "QA-41"
            ):
                raise ValueError(f"invalid QA handoff binding for {task['id']}")


def workers_from(config: dict[str, Any]) -> list[Worker]:
    workers: list[Worker] = []
    runtime_metrics = config.get("resource_metrics", {})
    for w in config["workers"]:
        routing = dict(w.get("routing", {}))
        observed = runtime_metrics.get(w["id"], {})
        if isinstance(observed, dict):
            routing.update(observed)
        resources = frozenset(w.get("resources", []))
        workers.append(
            Worker(
                id=w["id"],
                capabilities=frozenset(w.get("capabilities", [])),
                resources=resources,
                authority_max=int(w.get("authority_max", 0)),
                enabled=bool(w.get("enabled", True)),
                verifier=bool(w.get("verifier", False)),
                max_concurrent_tasks=max(1, int(w.get("max_concurrent_tasks", 1))),
                available=bool(routing.get("available", True)),
                health_score=float(routing.get("health_score", 1.0)),
                latency_ms=float(routing.get("latency_ms", 0.0)),
                failure_rate=float(routing.get("failure_rate", 0.0)),
                cost_units=float(routing.get("cost_units", 0.0)),
                data_locality=frozenset(routing.get("data_locality", [])),
                trust_domains=frozenset(routing.get("trust_domains", [])) or resources,
            )
        )
    return workers


def task_index(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["id"]: t for t in config["tasks"]}


def active_worker_load(config: dict[str, Any], *, exclude_task: dict[str, Any] | None = None) -> dict[str, int]:
    load: dict[str, int] = {}
    for task in config["tasks"]:
        if task is exclude_task:
            continue
        worker_id = task.get("assigned_worker")
        if task.get("status") in ACTIVE and worker_id:
            load[worker_id] = load.get(worker_id, 0) + 1
    return load


def dependencies_done(task: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> bool:
    return all(by_id[d].get("status") == "DONE" for d in task.get("dependencies", []))


def enforce_owner_boundaries(config: dict[str, Any]) -> None:
    """Fail closed for L4 tasks regardless of restored runtime status."""
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


def _routing_candidate(
    task: dict[str, Any],
    worker: Worker,
    *,
    verifier_only: bool,
    active_load: dict[str, int],
) -> dict[str, Any]:
    needed = set(task.get("required_capabilities", []))
    required_resources = set(task.get("required_resources", []))
    preferred = set(task.get("preferred_resources", []))
    required_locality = set(task.get("required_data_locality", []))
    preferred_locality = set(task.get("preferred_data_locality", []))
    required_trust = task.get("required_trust_domain")
    preferred_trust = set(task.get("preferred_trust_domains", []))
    producer = task.get("producer")
    load = int(active_load.get(worker.id, 0))
    reasons: list[str] = []

    if not worker.enabled:
        reasons.append("disabled")
    if not worker.available:
        reasons.append("unavailable")
    if worker.authority_max < int(task.get("authority", 0)):
        reasons.append("authority_insufficient")
    if verifier_only and not worker.verifier:
        reasons.append("not_verifier")
    if verifier_only and producer and worker.id == producer:
        reasons.append("producer_verifier_separation")
    missing_caps = sorted(needed - worker.capabilities)
    if missing_caps:
        reasons.append("missing_capabilities:" + ",".join(missing_caps))
    missing_resources = sorted(required_resources - worker.resources)
    if missing_resources:
        reasons.append("missing_required_resources:" + ",".join(missing_resources))
    if load >= worker.max_concurrent_tasks:
        reasons.append("capacity_exhausted")
    if worker.health_score < float(task.get("min_health_score", 0.0)):
        reasons.append("health_below_minimum")
    if "max_cost_units" in task and worker.cost_units > float(task["max_cost_units"]):
        reasons.append("cost_budget_exceeded")
    if required_locality and not required_locality.intersection(worker.data_locality | worker.resources):
        reasons.append("required_data_not_local")
    if required_trust and required_trust not in worker.trust_domains:
        reasons.append("trust_domain_mismatch")

    utilization = load / worker.max_concurrent_tasks
    preferred_resource_hits = len(preferred.intersection(worker.resources))
    locality_hits = len(preferred_locality.intersection(worker.data_locality | worker.resources))
    trust_hits = len(preferred_trust.intersection(worker.trust_domains))
    components = {
        "health": round(worker.health_score * 30.0, 6),
        "latency": round(-min(worker.latency_ms / 1000.0, 10.0) * 4.0, 6),
        "failure_rate": round(-worker.failure_rate * 30.0, 6),
        "cost": round(-worker.cost_units * 5.0, 6),
        "queue_depth": round(-utilization * 20.0, 6),
        "preferred_resource": float(preferred_resource_hits * 20),
        "data_locality": float(locality_hits * 15),
        "trust_domain": float(trust_hits * 10),
        "remaining_capacity": round((1.0 - utilization) * 5.0, 6),
    }
    score = round(sum(components.values()), 6)
    return {
        "worker_id": worker.id,
        "eligible": not reasons,
        "rejection_reasons": reasons,
        "score": score if not reasons else None,
        "components": components,
        "observed": {
            "available": worker.available,
            "health_score": worker.health_score,
            "latency_ms": worker.latency_ms,
            "failure_rate": worker.failure_rate,
            "cost_units": worker.cost_units,
            "queue_depth": load,
            "capacity": worker.max_concurrent_tasks,
            "data_locality": sorted(worker.data_locality),
            "trust_domains": sorted(worker.trust_domains),
        },
    }


def rank_worker_candidates(
    task: dict[str, Any],
    workers: list[Worker],
    *,
    verifier_only: bool = False,
    active_load: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    active_load = active_load or {}
    rows = [
        _routing_candidate(task, worker, verifier_only=verifier_only, active_load=active_load)
        for worker in workers
    ]
    rows.sort(
        key=lambda row: (
            not row["eligible"],
            -(row["score"] if row["score"] is not None else float("-inf")),
            row["worker_id"],
        )
    )
    return rows


def eligible_workers(
    task: dict[str, Any],
    workers: list[Worker],
    *,
    verifier_only: bool = False,
    active_load: dict[str, int] | None = None,
) -> list[Worker]:
    by_id = {worker.id: worker for worker in workers}
    return [
        by_id[row["worker_id"]]
        for row in rank_worker_candidates(task, workers, verifier_only=verifier_only, active_load=active_load)
        if row["eligible"]
    ]


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


def _waiting_external_snapshot(config: dict[str, Any], *, exclude_worker: str | None = None) -> list[dict[str, Any]]:
    rows = []
    for task in config["tasks"]:
        if task.get("external_wait_state") != WAITING_EXTERNAL:
            continue
        if exclude_worker and task.get("assigned_worker") == exclude_worker:
            continue
        rows.append(
            {
                "task_id": task["id"],
                "worker_id": task.get("assigned_worker"),
                "wait_started_at": task.get("external_wait_started_at"),
                "dispatch_id": task.get("dispatch_id"),
            }
        )
    return rows


def assign_ready_tasks(config: dict[str, Any], now: datetime) -> None:
    workers = workers_from(config)
    active_load = active_worker_load(config)
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

        qa_verifier_only = task.get("qa_verifier_only") is True
        if qa_verifier_only and task.get("qa_dispatch_enabled") is not True:
            task["routing_decision"] = {
                "evaluated_at": iso(now),
                "selected_worker": None,
                "reason": "independent_strategy_qa_worker_contract_not_enabled",
                "candidates": [],
            }
            task["blocked_reason"] = "independent strategy QA worker contract not enabled"
            continue
        routing_rows = rank_worker_candidates(
            task, workers, verifier_only=qa_verifier_only, active_load=active_load
        )
        eligible_rows = [row for row in routing_rows if row["eligible"]]
        if task.get("id") in TASKS:
            # Actual numerical Research leases are not generic cloud pytest
            # work: only the dedicated Research Agent can be their producer.
            eligible_rows = [row for row in eligible_rows
                             if row["worker_id"] == "research-agent"]
        if task.get("qa_verifier_only") is True:
            # Materialized QA-41 replay is verifier work from the outset. It
            # must never receive a generic producer lease.
            eligible_rows = [row for row in eligible_rows
                             if row["worker_id"] == task.get("required_verifier")
                             and row["worker_id"] == "qa-verifier-agent"]
        if not eligible_rows:
            task["routing_decision"] = {
                "evaluated_at": iso(now),
                "selected_worker": None,
                "reason": "no_eligible_worker",
                "candidates": routing_rows,
            }
            continue

        selected = eligible_rows[0]
        worker = next(worker for worker in workers if worker.id == selected["worker_id"])
        for row in routing_rows:
            row["selection_reason"] = (
                "highest_deterministic_score" if row["worker_id"] == worker.id
                else ("lower_score_than_selected" if row["eligible"] else "ineligible")
            )
        waiting = _waiting_external_snapshot(config, exclude_worker=worker.id)
        task["routing_decision"] = {
            "evaluated_at": iso(now),
            "selected_worker": worker.id,
            "selected_score": selected["score"],
            "reason": "highest_deterministic_score",
            "candidates": routing_rows,
        }
        if waiting:
            task["zero_idle_evidence"] = {
                "leased_at": iso(now),
                "overlapped_external_waits": waiting,
                "rule": "dispatch_independent_ready_work_while_other_resource_waits",
            }

        task["assigned_worker"] = worker.id
        if qa_verifier_only:
            task.pop("producer", None)
            task["verifier"] = worker.id
            task["status"] = "VERIFYING"
        else:
            task["producer"] = worker.id
            task["status"] = "LEASED"
        task["lease_id"] = str(uuid.uuid4())
        task["leased_at"] = iso(now)
        task["heartbeat_at"] = iso(now)
        task["lease_expires_at"] = iso(now + timedelta(minutes=DEFAULT_LEASE_MINUTES))
        task["attempt"] = int(task.get("attempt", 0)) + 1
        active_load[worker.id] = active_load.get(worker.id, 0) + 1
        active_count += 1
        if qa_verifier_only:
            emit(
                "verification_assigned",
                task_id=task["id"],
                verifier=worker.id,
                producer=task.get("qa_handoff_task", {}).get("producer_role"),
                routing_score=selected["score"],
            )
        else:
            emit(
                "task_leased",
                task_id=task["id"],
                worker=worker.id,
                attempt=task["attempt"],
                routing_score=selected["score"],
                overlapped_external_waits=[row["task_id"] for row in waiting],
            )


def route_triage(config: dict[str, Any], now: datetime) -> None:
    workers = workers_from(config)
    active_load = active_worker_load(config)
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
        if failure_class in {"startup_failure", "timed_out", "transient_network"} and int(task.get("transient_retries", 0)) < 1:
            task["transient_retries"] = int(task.get("transient_retries", 0)) + 1
            task["status"] = "READY"
            task["ready_at"] = iso(now)
            emit("bounded_transient_retry", task_id=task["id"])
            continue
        if task.get("id") in TASKS:
            # The numerical executor rejects generic RCA workers. Leasing the
            # same Research ID to an analyst only creates a deterministic loop.
            # Preserve the failure for reviewed recovery, never numeric success.
            prior_lease, prior_dispatch = task.get("lease_id"), task.get("dispatch_id")
            task["status"] = "BLOCKED"
            task["blocked_reason"] = RESEARCH_RCA_BLOCK_REASON
            task["triage_mode"] = "root_cause_first"
            for field in (
                "assigned_worker", "lease_id", "heartbeat_at", "lease_expires_at",
                "dispatch_id", "dispatch_transport", "dispatched_at",
                "external_wait_state", "external_wait_started_at",
            ):
                task[field] = None
            emit("research_rca_review_required", task_id=task["id"],
                 prior_lease_id=prior_lease, prior_dispatch_id=prior_dispatch)
            continue
        rca_caps = {"root_cause_analysis", "diagnostics"}
        candidates = [
            w
            for w in workers
            if w.enabled
            and w.authority_max >= int(task.get("authority", 0))
            and rca_caps.issubset(w.capabilities)
            and w.id != task.get("producer")
            and active_load.get(w.id, 0) < w.max_concurrent_tasks
        ]
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
        active_load[analyst.id] = active_load.get(analyst.id, 0) + 1
        emit("root_cause_assigned", task_id=task["id"], worker=analyst.id)


def request_verification(config: dict[str, Any], task: dict[str, Any], now: datetime) -> bool:
    if task.get("qa_verifier_only") is True:
        raise ValueError("verifier-only QA task cannot request a second verifier")
    if int(task.get("authority", 0)) >= 4:
        task["status"] = "OWNER_REQUIRED"
        task["blocked_reason"] = "L4 owner approval required"
        task["assigned_worker"] = None
        return False
    workers = workers_from(config)
    candidates = eligible_workers(
        task,
        workers,
        verifier_only=True,
        active_load=active_worker_load(config, exclude_task=task),
    )
    if task.get("id") in TASKS:
        # Reject a generic verifier even if its dynamic routing score is
        # higher: independent numerical replay requires the designated QA.
        candidates = [w for w in candidates if w.id == "qa-verifier-agent"]
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
            if task.get("qa_verifier_only") is True:
                handoff = task.get("qa_handoff_task")
                receipt = evidence.get("qa_receipt_digest")
                if (
                    worker_id != task.get("required_verifier")
                    or worker_id != task.get("verifier")
                    or task.get("producer") is not None
                    or not isinstance(handoff, Mapping)
                    or evidence.get("qa_lease_id") != task.get("lease_id")
                    or evidence.get("task_digest") != handoff.get("task_digest")
                    or evidence.get("source_sha") != handoff.get("source_sha")
                    or evidence.get("proposal_digest") != handoff.get("proposal_digest")
                    or evidence.get("proposal_result_digest") != handoff.get("proposal_result_digest")
                    or evidence.get("requalification_digest") != handoff.get("requalification_digest")
                    or evidence.get("requalification_verification_digest")
                    != handoff.get("requalification_verification_digest")
                    or evidence.get("strategy_config_digest") != handoff.get("strategy_config_digest")
                    or evidence.get("independent_qa_complete") is not True
                    or evidence.get("qualification_authority") is not False
                    or evidence.get("paper_execution_authority") is not False
                    or evidence.get("automatic_strategy_promotion") is not False
                    or evidence.get("live_trading_authority") is not False
                    or not isinstance(receipt, str)
                    or len(receipt) != 64
                    or any(ch not in "0123456789abcdef" for ch in receipt)
                ):
                    raise ValueError("independent Strategy QA receipt does not bind this exact verifier lease")
            if task_id in TASKS:
                original = task.get("result_evidence", {})
                if (
                    worker_id == task.get("producer")
                    or not isinstance(original, dict)
                    or evidence.get("independent_qa_complete") is not True
                    or evidence.get("auto_demo_promotion") is not False
                    or evidence.get("live_enabled") is not False
                    or evidence.get("producer_receipt_digest") != original.get("receipt_digest")
                    or evidence.get("producer_lease_id") != task.get("research_producer_lease_id")
                    or evidence.get("source_sha") != original.get("source_sha")
                    or not isinstance(evidence.get("qa_digest"), str)
                    or len(evidence["qa_digest"]) != 64
                ):
                    raise ValueError("independent Research QA has not verified this exact producer")
                if task_id in PREDECESSOR:
                    ancestor = validate_ancestry({k: task[k] for k in ANCESTRY if k in task})
                    if (
                        original.get("prior_ledger_digest") != ancestor["research_predecessor_ledger_digest"]
                        or original.get("mechanism") == ancestor["research_predecessor_mechanism"]
                    ):
                        raise ValueError("second Research QA did not prove causal frontier advancement")
            task["status"] = "DONE"
            task["verified_at"] = iso()
            task["verification_evidence"] = evidence
            emit("task_done", task_id=task_id, verifier=worker_id)
        else:
            # An independent QA lease has its own lease_id. Preserve the
            # producer's exact identity and digest to prevent QA from
            # accidentally verifying an unrelated/latest Research artifact.
            if task_id in TASKS:
                if (
                    not isinstance(evidence.get("receipt_digest"), str)
                    or len(evidence["receipt_digest"]) != 64
                    or evidence.get("independent_qa_complete") is not False
                    or evidence.get("auto_demo_promotion") is not False
                    or evidence.get("live_enabled") is not False
                ):
                    raise ValueError("real research producer receipt or authority invalid")
                if task_id in PREDECESSOR:
                    ancestor = validate_ancestry({k: task[k] for k in ANCESTRY if k in task})
                    if (
                        evidence.get("prior_ledger_digest") != ancestor["research_predecessor_ledger_digest"]
                        or evidence.get("mechanism") == ancestor["research_predecessor_mechanism"]
                    ):
                        raise ValueError("successor Research producer did not execute a different QA-bound mechanism")
                task["research_producer_lease_id"] = task["lease_id"]
            task["result_evidence"] = evidence
            request_verification(config, task, utcnow())
    elif outcome == "failure":
        if task.get("qa_verifier_only") is True:
            task["failure_class"] = evidence.get("failure_class", "independent_strategy_qa_failed")
            task["failure_evidence"] = evidence
            task["status"] = "BLOCKED"
            task["blocked_reason"] = "independent Strategy QA failed; reviewed fresh QA lease required"
            task["assigned_worker"] = None
            task["heartbeat_at"] = None
            task["lease_expires_at"] = None
            emit(
                "strategy_qa_failed_closed",
                task_id=task_id,
                verifier=worker_id,
                failure_class=task["failure_class"],
            )
            return
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
    workers = workers_from(config)
    active_load = active_worker_load(config)
    worker_capacity = {
        worker.id: {
            "active": active_load.get(worker.id, 0),
            "capacity": worker.max_concurrent_tasks,
            "available": max(0, worker.max_concurrent_tasks - active_load.get(worker.id, 0)),
        }
        for worker in workers if worker.enabled
    }
    unassigned_ready = [t["id"] for t in config["tasks"] if t.get("status") == "READY" and not t.get("assigned_worker")]
    return {
        "generated_at": iso(),
        "phase": config.get("phase"),
        "task_phases": sorted({int(t.get("phase", config.get("phase"))) for t in config["tasks"]}),
        "counts": counts,
        "verified_progress_percent": round((done / total * 100.0) if total else 0.0, 2),
        "owner_required": [t["id"] for t in config["tasks"] if t.get("status") == "OWNER_REQUIRED"],
        "worker_capacity": worker_capacity,
        "available_worker_slots": sum(item["available"] for item in worker_capacity.values()),
        "unassigned_ready": unassigned_ready,
        "external_waiting": [
            {
                "task_id": t["id"],
                "worker_id": t.get("assigned_worker"),
                "wait_started_at": t.get("external_wait_started_at"),
                "dispatch_id": t.get("dispatch_id"),
            }
            for t in config["tasks"] if t.get("external_wait_state") == WAITING_EXTERNAL
        ],
        "zero_idle_assignments": [
            {
                "task_id": t["id"],
                **t["zero_idle_evidence"],
            }
            for t in config["tasks"] if isinstance(t.get("zero_idle_evidence"), dict)
        ],
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
