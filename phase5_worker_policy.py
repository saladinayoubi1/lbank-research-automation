from __future__ import annotations

from dataclasses import dataclass
from typing import Any

WORKER_RUNTIME_SCHEMA = "nexus.phase5-worker-runtime.v1"
ROUTING_DECISION_SCHEMA = "nexus.phase5-routing-decision.v1"
HEALTH_STATES = {"online", "degraded", "offline"}
MAX_RUNTIME_WORKERS = 64
MAX_ESTIMATED_COST_USD = 10.0


class WorkerPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    worker_id: str
    trust_domain: str
    health: str
    active: int
    capacity: int
    estimated_cost_usd: float
    preferred_resource_matches: int


def _bounded_string(value: Any, field: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise WorkerPolicyError(f"{field} must be a non-empty bounded string")
    return value


def _registry(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    workers = config.get("workers")
    if not isinstance(workers, list) or len(workers) > MAX_RUNTIME_WORKERS:
        raise WorkerPolicyError("worker registry is malformed or exceeds bounded size")
    index: dict[str, dict[str, Any]] = {}
    for worker in workers:
        if not isinstance(worker, dict):
            raise WorkerPolicyError("worker registry entry must be an object")
        worker_id = _bounded_string(worker.get("id"), "worker.id")
        if worker_id in index:
            raise WorkerPolicyError("worker ids must be unique")
        trust_domain = _bounded_string(worker.get("trust_domain"), f"trust_domain for {worker_id}")
        authority = worker.get("authority_max")
        capacity = worker.get("max_concurrent_tasks", 1)
        if isinstance(authority, bool) or not isinstance(authority, int) or authority not in range(0, 5):
            raise WorkerPolicyError(f"invalid authority_max for {worker_id}")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1 or capacity > 64:
            raise WorkerPolicyError(f"invalid capacity for {worker_id}")
        capabilities = worker.get("capabilities", [])
        resources = worker.get("resources", [])
        if not isinstance(capabilities, list) or any(not isinstance(item, str) or not item for item in capabilities):
            raise WorkerPolicyError(f"invalid capabilities for {worker_id}")
        if not isinstance(resources, list) or any(not isinstance(item, str) or not item for item in resources):
            raise WorkerPolicyError(f"invalid resources for {worker_id}")
        normalized = dict(worker)
        normalized["trust_domain"] = trust_domain
        index[worker_id] = normalized
    return index


def validate_runtime_snapshot(config: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Validate dynamic worker state without allowing it to redefine authority/capabilities."""
    registry = _registry(config)
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != WORKER_RUNTIME_SCHEMA:
        raise WorkerPolicyError("worker runtime schema mismatch")
    workers = snapshot.get("workers")
    if not isinstance(workers, list) or len(workers) > MAX_RUNTIME_WORKERS:
        raise WorkerPolicyError("worker runtime list is malformed or exceeds bounded size")
    allowed = {
        "worker_id", "health", "active", "estimated_cost_usd", "paid_budget_authorized",
        "reason", "observed_at",
    }
    runtime: dict[str, dict[str, Any]] = {}
    for item in workers:
        if not isinstance(item, dict) or not set(item).issubset(allowed):
            raise WorkerPolicyError("worker runtime contains forbidden/static-authority fields")
        worker_id = _bounded_string(item.get("worker_id"), "worker runtime worker_id")
        if worker_id not in registry:
            raise WorkerPolicyError(f"unknown runtime worker {worker_id}")
        if worker_id in runtime:
            raise WorkerPolicyError("duplicate runtime worker")
        health = item.get("health")
        if health not in HEALTH_STATES:
            raise WorkerPolicyError(f"invalid health for {worker_id}")
        active = item.get("active", 0)
        if isinstance(active, bool) or not isinstance(active, int) or active < 0:
            raise WorkerPolicyError(f"invalid active count for {worker_id}")
        cost = item.get("estimated_cost_usd", 0.0)
        if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost < 0 or cost > MAX_ESTIMATED_COST_USD:
            raise WorkerPolicyError(f"invalid estimated cost for {worker_id}")
        paid = item.get("paid_budget_authorized", False)
        if not isinstance(paid, bool):
            raise WorkerPolicyError(f"paid_budget_authorized must be boolean for {worker_id}")
        runtime[worker_id] = {
            "health": health,
            "active": active,
            "estimated_cost_usd": float(cost),
            "paid_budget_authorized": paid,
            "reason": item.get("reason"),
            "observed_at": item.get("observed_at"),
        }
    return runtime


def route_task(
    config: dict[str, Any],
    task: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    max_cost_usd: float = 0.0,
) -> dict[str, Any]:
    registry = _registry(config)
    runtime = validate_runtime_snapshot(config, snapshot)
    authority = task.get("authority", 0)
    if isinstance(authority, bool) or not isinstance(authority, int) or authority not in range(0, 5):
        raise WorkerPolicyError("task authority is invalid")
    if authority >= 4:
        return {
            "schema_version": ROUTING_DECISION_SCHEMA,
            "task_id": task.get("id"),
            "status": "owner_required",
            "worker_id": None,
            "reason": "L4_owner_required",
        }
    if isinstance(max_cost_usd, bool) or not isinstance(max_cost_usd, (int, float)) or max_cost_usd < 0:
        raise WorkerPolicyError("max_cost_usd is invalid")

    needed = set(task.get("required_capabilities", []))
    preferred = set(task.get("preferred_resources", []))
    candidates: list[Candidate] = []
    rejection_reasons: dict[str, str] = {}
    for worker_id, worker in registry.items():
        if not bool(worker.get("enabled", True)):
            rejection_reasons[worker_id] = "disabled"
            continue
        if int(worker["authority_max"]) < authority:
            rejection_reasons[worker_id] = "authority_insufficient"
            continue
        if not needed.issubset(set(worker.get("capabilities", []))):
            rejection_reasons[worker_id] = "capability_mismatch"
            continue
        state = runtime.get(worker_id)
        if state is None:
            rejection_reasons[worker_id] = "runtime_unknown"
            continue
        if state["health"] == "offline":
            rejection_reasons[worker_id] = "worker_offline"
            continue
        capacity = int(worker.get("max_concurrent_tasks", 1))
        if state["active"] >= capacity:
            rejection_reasons[worker_id] = "capacity_exhausted"
            continue
        cost = state["estimated_cost_usd"]
        # Paid/external providers are fail-closed unless an already-approved
        # bounded budget path says this specific dispatch may spend.
        if worker.get("trust_domain") == "deepseek-external" and not state["paid_budget_authorized"]:
            rejection_reasons[worker_id] = "paid_budget_not_authorized"
            continue
        if cost > float(max_cost_usd):
            rejection_reasons[worker_id] = "cost_budget_exceeded"
            continue
        candidates.append(
            Candidate(
                worker_id=worker_id,
                trust_domain=worker["trust_domain"],
                health=state["health"],
                active=state["active"],
                capacity=capacity,
                estimated_cost_usd=cost,
                preferred_resource_matches=len(preferred.intersection(worker.get("resources", []))),
            )
        )

    if not candidates:
        return {
            "schema_version": ROUTING_DECISION_SCHEMA,
            "task_id": task.get("id"),
            "status": "blocked",
            "worker_id": None,
            "reason": "no_eligible_worker",
            "rejections": dict(sorted(rejection_reasons.items())),
        }

    health_rank = {"online": 0, "degraded": 1}
    candidates.sort(
        key=lambda candidate: (
            health_rank[candidate.health],
            -candidate.preferred_resource_matches,
            candidate.estimated_cost_usd,
            candidate.active / candidate.capacity,
            candidate.worker_id,
        )
    )
    selected = candidates[0]
    return {
        "schema_version": ROUTING_DECISION_SCHEMA,
        "task_id": task.get("id"),
        "status": "routed",
        "worker_id": selected.worker_id,
        "trust_domain": selected.trust_domain,
        "health": selected.health,
        "estimated_cost_usd": selected.estimated_cost_usd,
        "reason": "best_bounded_candidate",
        "rejections": dict(sorted(rejection_reasons.items())),
    }
