from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import agent_manager as am

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")
SPECIALIZED_REASONING_FAILURE = "specialized_reasoning_provider_required"
SPECIALIZED_REASONING_BLOCK_REASON = "specialized reasoning provider required; no authorized reasoning route available"
DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS = {"P4-EVENT-001"}
STATE_BINDING_KEYS = (
    "phase",
    "gate",
    "dependencies",
    "required_capabilities",
    "authority",
    "acceptance",
)


def _definition_changed(current: dict[str, Any], previous: dict[str, Any]) -> bool:
    return any(current.get(key) != previous.get(key) for key in STATE_BINDING_KEYS)


def merge_definition(template: dict[str, Any], runtime: dict[str, Any] | None) -> dict[str, Any]:
    if not runtime or runtime.get("schema_version") != template.get("schema_version"):
        return deepcopy(template)

    merged = deepcopy(template)
    if isinstance(runtime.get("resource_metrics"), dict):
        merged["resource_metrics"] = deepcopy(runtime["resource_metrics"])
    if runtime.get("resource_metrics_updated_at"):
        merged["resource_metrics_updated_at"] = runtime["resource_metrics_updated_at"]

    old_by_id = {t["id"]: t for t in runtime.get("tasks", []) if isinstance(t, dict) and t.get("id")}
    new_ids = {t["id"] for t in merged.get("tasks", [])}
    definition_keys = {
        "id", "title", "phase", "gate", "priority", "dependencies",
        "required_capabilities", "preferred_resources", "required_resources",
        "required_data_locality", "preferred_data_locality",
        "required_trust_domain", "preferred_trust_domains",
        "min_health_score", "max_cost_units", "authority", "acceptance"
    }
    runtime_keys = {
        "status", "ready_at", "assigned_worker", "producer", "verifier", "lease_id",
        "leased_at", "heartbeat_at", "lease_expires_at", "attempt", "transient_retries",
        "triage_reason", "triage_started_at", "triage_mode", "triage_evidence", "required_output",
        "failure_class", "failure_evidence", "result_evidence", "verification_evidence",
        "verified_at", "blocked_reason", "dispatch_id", "dispatch_transport", "dispatched_at",
        "dispatch_mode", "offline_dispatch_digest", "offline_dispatch_bundle_created_at",
        "offline_result_bundle_ingested", "offline_result_bundle_digest",
        "result_artifact_ingested", "result_received_at", "routing_decision",
        "zero_idle_evidence", "waiting_from_status", "external_wait_state", "external_wait_started_at",
        "external_wait_completed_at", "external_wait_timeline"
    }
    for task in merged.get("tasks", []):
        old = old_by_id.get(task["id"])
        if not old:
            continue
        if _definition_changed(task, old):
            continue
        for key in runtime_keys:
            if key in old:
                task[key] = deepcopy(old[key])
        for key in definition_keys:
            if key in task:
                continue
            if key in old:
                task[key] = deepcopy(old[key])

    for old_id, old in old_by_id.items():
        if old_id in new_ids:
            continue
        historical = deepcopy(old)
        historical["status"] = "QUARANTINED"
        historical["blocked_reason"] = "task removed from current repository definition"
        merged["tasks"].append(historical)
    return merged


def apply_provider_gates(config: dict[str, Any]) -> None:
    """Keep paid providers unavailable unless the coordinator has explicit authority."""
    if os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1":
        return
    for worker in config.get("workers", []):
        if "deepseek" in worker.get("resources", []):
            worker["enabled"] = False


def _latest_external_worker(task: dict[str, Any]) -> str | None:
    timeline = task.get("external_wait_timeline")
    if isinstance(timeline, list) and timeline:
        latest = timeline[-1]
        if isinstance(latest, dict) and isinstance(latest.get("worker_id"), str):
            return latest["worker_id"]
    worker = task.get("assigned_worker")
    return worker if isinstance(worker, str) else None


def recover_completed_root_cause_analysis(config: dict[str, Any]) -> int:
    """Turn successful RCA work back into original-task work instead of false completion."""
    recovered = 0
    for task in config.get("tasks", []):
        if task.get("triage_mode") != "root_cause_first":
            continue
        if task.get("status") not in {"VERIFYING", "BLOCKED"}:
            continue
        evidence = task.get("result_evidence")
        if not isinstance(evidence, dict):
            continue

        task["triage_evidence"] = {
            "worker_id": _latest_external_worker(task),
            "received_at": task.get("result_received_at"),
            "evidence": deepcopy(evidence),
        }
        task["status"] = "READY"
        task["ready_at"] = am.iso()
        task["assigned_worker"] = None
        task["verifier"] = None
        task["lease_id"] = None
        task["leased_at"] = None
        task["heartbeat_at"] = None
        task["lease_expires_at"] = None
        task["blocked_reason"] = None
        task["triage_mode"] = None
        task["required_output"] = None
        task["result_evidence"] = None
        task["result_artifact_ingested"] = False
        task["result_received_at"] = None
        task["dispatch_id"] = None
        task["dispatch_transport"] = None
        task["dispatched_at"] = None
        task["external_wait_state"] = None
        task["external_wait_started_at"] = None
        am.emit("root_cause_completed_requeue", task_id=task["id"])
        recovered += 1
    return recovered


def block_unroutable_specialized_reasoning(config: dict[str, Any]) -> int:
    """Stop deterministic redispatch loops while preserving prior dispatch/failure audit evidence."""
    blocked = 0
    for task in config.get("tasks", []):
        if task.get("failure_class") != SPECIALIZED_REASONING_FAILURE:
            continue
        if task.get("id") in DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS:
            continue
        if task.get("status") not in {"TRIAGE", "READY", "BLOCKED"}:
            continue
        if task.get("status") == "BLOCKED" and task.get("blocked_reason") == SPECIALIZED_REASONING_BLOCK_REASON:
            continue

        prior_worker = task.get("assigned_worker")
        prior_dispatch_id = task.get("dispatch_id")
        prior_dispatch_transport = task.get("dispatch_transport")
        prior_dispatched_at = task.get("dispatched_at")
        task["status"] = "BLOCKED"
        task["blocked_reason"] = SPECIALIZED_REASONING_BLOCK_REASON
        task["triage_mode"] = "fail_closed_specialized_reasoning_provider"
        task["assigned_worker"] = None
        task["verifier"] = None
        task["lease_id"] = None
        task["leased_at"] = None
        task["heartbeat_at"] = None
        task["lease_expires_at"] = None
        task["dispatch_id"] = None
        task["dispatch_transport"] = None
        task["dispatched_at"] = None
        task["external_wait_state"] = None
        task["external_wait_started_at"] = None
        am.emit(
            "specialized_reasoning_blocked",
            task_id=task["id"],
            prior_worker=prior_worker,
            failure_class=SPECIALIZED_REASONING_FAILURE,
            dispatch_id=prior_dispatch_id,
            dispatch_transport=prior_dispatch_transport,
            dispatched_at=prior_dispatched_at,
        )
        blocked += 1
    return blocked


def recover_bounded_specialized_reasoning(config: dict[str, Any]) -> int:
    """Release only an exact prior block that now has a bounded deterministic proof."""
    recovered = 0
    for task in config.get("tasks", []):
        if task.get("id") not in DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS:
            continue
        if task.get("failure_class") != SPECIALIZED_REASONING_FAILURE:
            continue
        if task.get("status") != "BLOCKED":
            continue
        if task.get("blocked_reason") != SPECIALIZED_REASONING_BLOCK_REASON:
            continue

        task["status"] = "READY"
        task["ready_at"] = am.iso()
        task["blocked_reason"] = None
        task["triage_mode"] = None
        am.emit(
            "specialized_reasoning_bounded_recovery_ready",
            task_id=task["id"],
            failure_class=SPECIALIZED_REASONING_FAILURE,
        )
        recovered += 1
    return recovered


def load_runtime(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Durable wrapper for the NEXUS agent manager")
    parser.add_argument("--config", default=str(am.QUEUE_PATH))
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    args = parser.parse_args()

    template = am.load_config(Path(args.config))
    config = merge_definition(template, load_runtime(Path(args.runtime)))
    apply_provider_gates(config)
    recover_completed_root_cause_analysis(config)
    recover_bounded_specialized_reasoning(config)
    block_unroutable_specialized_reasoning(config)
    summary = am.cycle(config)
    am.atomic_json(Path(args.runtime), config)
    am.atomic_json(Path(args.summary), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
