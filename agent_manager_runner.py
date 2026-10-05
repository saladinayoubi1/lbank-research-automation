from __future__ import annotations

import argparse
import json
import os
import re
from urllib.parse import quote
from copy import deepcopy
from pathlib import Path
from typing import Any

import agent_manager as am
from nexus_research_missions import (FIRST, SECOND, THIRD, TASKS, PREDECESSOR, ANCESTRY, attested_predecessor, validate_ancestry)
from scripts.nexus_research_qa_incident_recovery import SPEC as RESEARCH_QA_INCIDENT_SPEC, load_spec as load_research_qa_incident, recover_incident as recover_research_qa_incident
from scripts.nexus_research_input_incident_recovery import SPEC as RESEARCH_INPUT_INCIDENT_SPEC, load_spec as load_research_input_incident, recover_incident as recover_research_input_incident
from nexus_strategy_qa_task_materializer import materialize_qa_tasks
from nexus_strategy_review_qa_handoff import verify_handoff

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")
SPECIALIZED_REASONING_FAILURE = "specialized_reasoning_provider_required"
SPECIALIZED_REASONING_BLOCK_REASON = "specialized reasoning provider required; no authorized reasoning route available"
DETERMINISTIC_SPECIALIZED_RECOVERY_WORKLOADS = {"P4-EVENT-001", "P4-UI-001"}
STATE_BINDING_KEYS = (
    "phase",
    "gate",
    "dependencies",
    "required_capabilities",
    "required_resources",
    "qa_verifier_only",
    "qa_dispatch_enabled",
    "required_verifier",
    "qa_handoff_task",
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
        "min_health_score", "max_cost_units", "authority", "acceptance",
        "qa_verifier_only", "qa_dispatch_enabled", "required_verifier", "qa_handoff_task"
    }
    runtime_keys = {
        "status", "ready_at", "assigned_worker", "producer", "verifier", "lease_id",
        "leased_at", "heartbeat_at", "lease_expires_at", "attempt", "transient_retries",
        "triage_reason", "triage_started_at", "triage_mode", "triage_evidence", "required_output",
        "failure_class", "failure_evidence", "result_evidence", "verification_evidence",
        "verified_at", "blocked_reason", "dispatch_id", "dispatch_transport", "dispatched_at",
        "dispatch_mode", "offline_dispatch_digest", "offline_dispatch_bundle_created_at",
        "offline_result_bundle_ingested", "offline_result_bundle_digest",
        "result_artifact_ingested", "result_received_at", "research_producer_lease_id",
        "research_cache_requested_sha", "research_cache_requested_binding", "research_cache_recovery_count", "research_cache_race_evidence", "research_qa_epoch_drift", "research_qa_incident_recovery", "routing_decision",
        "research_input_incident_recovery",
        *ANCESTRY,
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
        # When an old independent Research QA lease failed before producing
        # a result, this is still the ORIGINAL numeric producer receipt.
        # Never misclassify it as a successful generic RCA and erase it.
        if task.get("id") in TASKS and evidence.get("executor") == "nexus-real-composite-backtest":
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



# The reviewed multi-timeframe workflow is the ONLY producer of immutable
# replay + novelty-input transport. Never lease Research before it publishes
# the exact current main SHA. Cache presence is a scheduling hint only: the
# worker still checks full replay/delivery/ledger cryptographic provenance.
RESEARCH_TASK = FIRST
RESEARCH_WAIT = "waiting_for_source_exact_immutable_research_input_cache"
RESEARCH_CACHE_PREFIX = "nexus-composite-inputs-v2-"
RESEARCH_BOOTSTRAP_CACHE_PREFIX = "nexus-composite-inputs-v1-"
RESEARCH_WORKFLOW = "nexus_multitimeframe_strategy_discovery.yml"
RESEARCH_FIRST_MISS = "required immutable input or evidence is not a regular file"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _research_context() -> tuple[str, str] | None:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    sha = os.environ.get("GITHUB_SHA", "")
    ref = os.environ.get("GITHUB_REF", "")
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo)
        or not _SHA40.fullmatch(sha)
        or ref != "refs/heads/main"
        or not (os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN"))
    ):
        return None
    return repo, sha



def bind_qa_attested_successor(config: dict[str, Any]) -> str:
    """Source-exact QA-authorized successor chain, durable across cold restarts."""
    tasks = {t.get("id"): t for t in config.get("tasks", [])}
    state = "not_present"
    for new_id, old_id in PREDECESSOR.items():
        prior, successor = tasks.get(old_id), tasks.get(new_id)
        if prior is None or successor is None:
            continue
        if prior.get("status") != "DONE":
            return "awaiting_prior_QA" if state == "not_present" else state
        try:
            evidence = attested_predecessor(prior)
        except ValueError:
            if successor.get("status") in {"PENDING", "READY", "BLOCKED"}:
                successor["status"] = "BLOCKED"
                successor["blocked_reason"] = "predecessor_independent_research_QA_attestation_missing"
                am.emit("successor_research_QA_untrusted", task_id=new_id)
            return "untrusted_prior_QA"
        existing = {key: successor[key] for key in ANCESTRY if key in successor}
        if any(evidence[key] != value for key, value in existing.items()):
            raise ValueError("persisted research successor ancestry changed since the prior QA lease")
        if len(existing) != len(ANCESTRY):
            if successor.get("status") not in {"PENDING", "READY", "BLOCKED"}:
                raise ValueError("active successor is missing an immutable QA ancestry binding")
            successor.update(evidence)
            am.emit(
                "QA_verified_research_successor_bound", task_id=new_id,
                predecessor_lease_id=prior.get("research_producer_lease_id"),
                predecessor_QA_digest=evidence["research_predecessor_qa_digest"],
            )
            state = "QA_attested_successor_bound"
        else:
            validate_ancestry(existing)
            state = "QA_attested_successor_unchanged"
    return state


def _active_research_task(config: dict[str, Any]) -> dict[str, Any] | None:
    tasks = {t.get("id"): t for t in config.get("tasks", []) if isinstance(t, dict)}
    task = tasks.get(FIRST)
    for next_id in PREDECESSOR:
        if task is None or task.get("status") != "DONE":
            break
        task = tasks.get(next_id)
    return task


def _research_cache_binding(config: dict[str, Any], sha: str) -> tuple[str, str] | None:
    task = _active_research_task(config)
    if task is None:
        return None
    digest = task.get("research_predecessor_ledger_digest")
    if task.get("id") == FIRST and not digest:
        return RESEARCH_BOOTSTRAP_CACHE_PREFIX + sha, ""
    if not _HEX64.fullmatch(str(digest or "")):
        return None
    return RESEARCH_CACHE_PREFIX + sha + "-" + str(digest), str(digest)


def research_cache_status(config: dict[str, Any]) -> tuple[bool, str]:
    """Only metadata readiness; the bounded worker separately verifies bytes."""
    context = _research_context()
    if context is None:
        return False, "not_on_authorized_main_with_token"
    repo, sha = context
    binding = _research_cache_binding(config, sha)
    if binding is None:
        return False, "qa_attested_frontier_binding_unavailable"
    key, _ledger_digest = binding
    from agent_transport import _api

    try:
        response = _api(
            "GET",
            f"https://api.github.com/repos/{repo}/actions/caches?"
            f"key={quote(key)}&ref=refs%2Fheads%2Fmain&per_page=20",
        )
        rows = response.get("actions_caches", []) if isinstance(response, dict) else []
        if not isinstance(rows, list):
            return False, "invalid_cache_metadata"
        if any(
            isinstance(row, dict) and row.get("key") == key
            and row.get("ref") == "refs/heads/main"
            and type(row.get("size_in_bytes")) is int
            and row["size_in_bytes"] > 0
            for row in rows
        ):
            return True, "source_exact_transport_cache_present"
        return False, "source_exact_transport_cache_absent"
    except (RuntimeError, OSError, ValueError) as exc:
        return False, f"source_exact_cache_metadata_unavailable:{type(exc).__name__}"


def _observed_initial_cache_race(task: dict[str, Any]) -> bool:
    evidence = task.get("failure_evidence")
    return bool(
        task.get("id") in TASKS
        and int(task.get("attempt", 0)) == 1
        and int(task.get("research_cache_recovery_count", 0)) == 0
        and task.get("failure_class") == "verified_research_execution_failed"
        and isinstance(evidence, dict)
        and evidence.get("executor") == "nexus-real-composite-backtest"
        and evidence.get("reason") == RESEARCH_FIRST_MISS
        and evidence.get("auto_demo_promotion") is False
        and evidence.get("live_enabled") is False
    )


def _clear_abandoned_research_lease(task: dict[str, Any]) -> None:
    """A replaced lease is rejected by ordinary lease-bound ingestion."""
    for field in (
        "assigned_worker", "verifier", "lease_id", "leased_at", "heartbeat_at",
        "lease_expires_at", "dispatch_id", "dispatch_transport", "dispatched_at",
        "external_wait_state", "external_wait_started_at",
        "result_received_at",
    ):
        task[field] = None
    task["result_artifact_ingested"] = False
    task["triage_mode"] = None
    task["required_output"] = None


def apply_research_input_gate(config: dict[str, Any], *, ready: bool) -> str:
    """Park only this exact task and recover ONE observed pre-cache first lease.

    Never turn untrusted/failing numeric research into success. Refuse retries
    after a second or different failure; independent RCA remains mandatory.
    """
    tasks = {t.get("id"): t for t in config.get("tasks", [])}
    first = tasks.get(FIRST)
    if first is None:
        return "not_present"
    task = first
    for next_id in PREDECESSOR:
        if task.get("status") != "DONE":
            break
        candidate = tasks.get(next_id)
        if candidate is None:
            return "terminal_unchanged"
        evidence = {key: candidate[key] for key in ANCESTRY if key in candidate}
        try:
            validate_ancestry(evidence)
            if evidence != attested_predecessor(task):
                raise ValueError("successor ancestry differs from previous independent QA")
        except ValueError:
            if candidate.get("status") in {"PENDING", "READY", "BLOCKED"}:
                candidate["status"] = "BLOCKED"
                candidate["blocked_reason"] = "predecessor_independent_research_QA_attestation_missing"
            return "successor_QA_not_attested"
        task = candidate
        if task.get("status") in {"QUARANTINED", "OWNER_REQUIRED"}:
            return "successor_terminal_unchanged"
    status = task.get("status")
    if status in {"DONE", "QUARANTINED", "OWNER_REQUIRED"}:
        return "terminal_unchanged"

    first_race = _observed_initial_cache_race(task)
    if status in {"TRIAGE", "RUNNING", "BLOCKED"} and first_race:
        if status == "RUNNING" and task.get("triage_mode") != "root_cause_first":
            return "active_producer_unchanged"
        if status == "BLOCKED" and task.get("blocked_reason") not in {
            RESEARCH_WAIT, "independent root-cause analyst unavailable",
        }:
            return "unrelated_block_unchanged"
        task["research_cache_race_evidence"] = {
            "first_failed_lease_id": task.get("lease_id"),
            "first_failure": deepcopy(task.get("failure_evidence")),
            "previous_status": status,
            "previous_triage_mode": task.get("triage_mode"),
        }
        _clear_abandoned_research_lease(task)
        task["status"] = "BLOCKED"
        task["blocked_reason"] = RESEARCH_WAIT
        task["research_cache_recovery_count"] = 1
        am.emit("research_first_source_cache_race_parked", task_id=task.get("id"))
        status = "BLOCKED"

    if not ready:
        if status in {"PENDING", "READY"}:
            task["status"] = "BLOCKED"
            task["blocked_reason"] = RESEARCH_WAIT
            am.emit("research_waiting_for_verified_input_transport", task_id=task.get("id"))
            return "parked_waiting_cache"
        return "wait_unchanged"

    if status == "BLOCKED" and task.get("blocked_reason") == RESEARCH_WAIT:
        task["status"] = "READY"
        task["ready_at"] = am.iso()
        task["blocked_reason"] = None
        am.emit(
            "research_source_cache_ready_released",
            task_id=task.get("id"),
            recovery_count=int(task.get("research_cache_recovery_count", 0)),
        )
        return "ready_for_producer_lease"
    return "ready_no_change"


def request_missing_research_cache(config: dict[str, Any], reason: str) -> str:
    """One bounded main-only request; never blindly restart failed workflows."""
    context = _research_context()
    tasks = {t.get("id"): t for t in config.get("tasks", [])}
    task = tasks.get(FIRST)
    for next_id in PREDECESSOR:
        if task is not None and task.get("status") == "DONE":
            task = tasks.get(next_id)
    if context is None or task is None or task.get("blocked_reason") != RESEARCH_WAIT:
        return "not_requested"
    if reason not in {"source_exact_transport_cache_absent"}:
        return "metadata_unverified_no_dispatch"
    repo, sha = context
    binding = _research_cache_binding(config, sha)
    if binding is None:
        return "metadata_unverified_no_dispatch"
    cache_key, ledger_digest = binding
    binding_token = cache_key
    from agent_transport import _api

    try:
        runs = _api(
            "GET",
            f"https://api.github.com/repos/{repo}/actions/workflows/"
            f"{RESEARCH_WORKFLOW}/runs?branch=main&per_page=30",
        )
        matches = [
            row for row in runs.get("workflow_runs", [])
            if isinstance(row, dict) and row.get("head_sha") == sha
            and row.get("head_branch") == "main"
            and row.get("event") in {"push", "workflow_dispatch"}
        ]
        if any(row.get("status") != "completed" for row in matches):
            task["research_cache_requested_sha"] = sha
            return "matching_research_workflow_already_running"
        if task.get("research_cache_requested_binding") == binding_token:
            return "prior_dispatch_pending_no_duplicate"
        if matches and not any(row.get("conclusion") == "success" for row in matches):
            return "matching_research_workflow_failed_review_required"
        if not ledger_digest and any(row.get("conclusion") == "success" for row in matches):
            return "successful_workflow_cache_pending_or_missing"
        _api(
            "POST",
            f"https://api.github.com/repos/{repo}/actions/workflows/"
            f"{RESEARCH_WORKFLOW}/dispatches",
            {"ref": "main"},
        )
        task["research_cache_requested_sha"] = sha
        task["research_cache_requested_binding"] = binding_token
        am.emit(
            "source_exact_research_cache_build_dispatched",
            task_id=task["id"],
            source_sha=sha,
            predecessor_ledger_digest=ledger_digest,
        )
        return "source_exact_cache_build_dispatched"
    except (RuntimeError, OSError, ValueError) as exc:
        return f"research_cache_build_unavailable:{type(exc).__name__}"



def load_runtime(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _load_regular_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4_000_000:
        raise ValueError("Strategy QA durable evidence is missing, linked, or oversized")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Strategy QA durable evidence is unreadable") from exc
    if not isinstance(value, dict):
        raise ValueError("Strategy QA durable evidence must be an object")
    return value


def materialize_strategy_qa_store(template: dict[str, Any], store: Path) -> dict[str, Any]:
    if not store.exists():
        return deepcopy(template)
    if store.is_symlink() or not store.is_dir():
        raise ValueError("Strategy QA durable evidence store is invalid")

    result = deepcopy(template)
    for directory in sorted(store.iterdir(), key=lambda path: path.name):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Strategy QA durable evidence contains an invalid entry")
        if not re.fullmatch(r"[0-9a-f]{64}", directory.name):
            raise ValueError("Strategy QA durable evidence directory identity is malformed")
        handoff = _load_regular_json(directory / "qa-handoff.json")
        verification = _load_regular_json(directory / "qa-handoff-verification.json")
        if handoff.get("handoff_digest") != directory.name:
            raise ValueError("Strategy QA durable evidence path does not match handoff digest")
        if verify_handoff(handoff) != verification or verification.get("decision") != "pass":
            raise ValueError("Strategy QA durable evidence verification failed")
        result = materialize_qa_tasks(result, handoff, verification)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Durable wrapper for the NEXUS agent manager")
    parser.add_argument("--config", default=str(am.QUEUE_PATH))
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    parser.add_argument(
        "--strategy-qa-store",
        default="data/agent_coordination/strategy_qa_handoffs",
    )
    args = parser.parse_args()

    template = am.load_config(Path(args.config))
    template = materialize_strategy_qa_store(template, Path(args.strategy_qa_store))
    config = merge_definition(template, load_runtime(Path(args.runtime)))
    apply_provider_gates(config)
    recover_completed_root_cause_analysis(config)
    recover_bounded_specialized_reasoning(config)
    block_unroutable_specialized_reasoning(config)
    research_context = _research_context()
    incident_recovered = False
    if research_context is not None and RESEARCH_QA_INCIDENT_SPEC.is_file():
        from agent_transport import _api
        incident_recovered = recover_research_qa_incident(
            config, spec=load_research_qa_incident(),
            api_get=lambda endpoint: _api("GET", "https://api.github.com/" + endpoint),
            current_sha=research_context[1],
        )
    successor_status = bind_qa_attested_successor(config)
    input_incident_recovered = False
    if research_context is not None and RESEARCH_INPUT_INCIDENT_SPEC.is_file():
        from agent_transport import _api
        input_incident_recovered = recover_research_input_incident(
            config, spec=load_research_input_incident(),
            api_get=lambda endpoint: _api("GET", "https://api.github.com/" + endpoint),
            current_sha=research_context[1],
        )
    cache_ready, cache_reason = research_cache_status(config)
    cache_gate = apply_research_input_gate(config, ready=cache_ready)
    cache_build = request_missing_research_cache(config, cache_reason) if not cache_ready else "ready"
    summary = am.cycle(config)
    summary["research_input_gate"] = {
        "ready": cache_ready,
        "successor": successor_status,
        "verified_fifth_qa_incident_released": incident_recovered,
        "verified_tenth_input_incident_requeued": input_incident_recovered,
        "reason": cache_reason,
        "action": cache_gate,
        "cache_build": cache_build,
        "research_only": True,
        "automatic_paper_promotion": False,
        "live_trading_enabled": False,
    }
    am.atomic_json(Path(args.runtime), config)
    am.atomic_json(Path(args.summary), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
