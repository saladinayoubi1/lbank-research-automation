"""One-shot source-epoch QA recovery for the exact verified fifth Research incident.

This is NOT a generic completed-task recovery, strategy admission or permission
to waive independent numerical QA. GitHub is only consulted as source/run
evidence; the existing NEXUS manager still owns task and lease lifecycle.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

import agent_manager as am
from nexus_research_missions import FIFTH, FOURTH, ANCESTRY, attested_predecessor

REPO = "saladinayoubi1/lbank-research-automation"
SPEC = Path(".nexus/recovery/research-fifth-qa-source-epoch-v1.json")
SCHEMA = "nexus.research-qa-incident-recovery.v1"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
EXPECTED_SPEC_KEYS = {
    "schema", "task_id", "producer_source_sha", "producer_lease_id",
    "producer_receipt_digest", "failed_qa_lease_id", "failed_qa_dispatch_id",
    "failed_qa_run_id", "failed_qa_head_sha", "reason",
    "allow_original_source_qa_only", "automatic_demo_promotion", "live_enabled",
}


class ResearchQaIncidentError(ValueError):
    pass


def load_spec(path: Path = SPEC) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ResearchQaIncidentError("exact reviewed QA recovery contract absent or unsafe")
    spec = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(spec, dict) or set(spec) != EXPECTED_SPEC_KEYS
            or spec.get("schema") != SCHEMA or spec.get("task_id") != FIFTH
            or not SHA40.fullmatch(str(spec.get("producer_source_sha", "")))
            or not SHA40.fullmatch(str(spec.get("failed_qa_head_sha", "")))
            or spec["producer_source_sha"] == spec["failed_qa_head_sha"]
            or not SHA64.fullmatch(str(spec.get("producer_receipt_digest", "")))
            or not all(isinstance(spec.get(k), str)
                       and re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", spec[k])
                       for k in ("producer_lease_id", "failed_qa_lease_id"))
            or not re.fullmatch(r"[0-9a-f]{32}", str(spec.get("failed_qa_dispatch_id", "")))
            or type(spec.get("failed_qa_run_id")) is not int
            or spec["failed_qa_run_id"] < 1
            or not isinstance(spec.get("reason"), str)
            or not 30 <= len(spec["reason"]) <= 500
            or spec["allow_original_source_qa_only"] is not True
            or spec["automatic_demo_promotion"] is not False
            or spec["live_enabled"] is not False):
        raise ResearchQaIncidentError("reviewed recovery manifest schema or safety invalid")
    return spec


def _old_qa_run_fail_closed(
    run: dict[str, Any], jobs: dict[str, Any], spec: dict[str, Any],
    qa_event: dict[str, Any],
) -> None:
    if (not isinstance(run, dict)
            or run.get("id") != spec["failed_qa_run_id"]
            or run.get("name") != "NEXUS Runtime Worker"
            or run.get("path") != ".github/workflows/nexus-runtime-worker.yml"
            or run.get("head_branch") != "main"
            or run.get("head_sha") != spec["failed_qa_head_sha"]
            or run.get("status") != "completed"
            or run.get("conclusion") != "failure"
            or run.get("event") != "workflow_dispatch"
            or (run.get("repository") or {}).get("full_name") != REPO
            or (run.get("head_repository") or {}).get("full_name") != REPO
            or (run.get("actor") or {}).get("login") != "github-actions[bot]"
            or not isinstance(jobs, dict)
            or not isinstance(jobs.get("jobs"), list)):
        raise ResearchQaIncidentError("original rejected QA run metadata is untrusted")
    errors = [s.get("name") for job in jobs["jobs"]
              if isinstance(job, dict) and job.get("name") == "preflight"
              and job.get("conclusion") == "failure"
              for s in (job.get("steps") or [])
              if isinstance(s, dict) and s.get("conclusion") == "failure"]
    if "Inspect authorized real Research Agent lease before expensive cache restores" not in errors:
        raise ResearchQaIncidentError("original rejected QA did not fail at inspected identity gate")
    try:
        recorded = datetime.fromisoformat(qa_event["started_at"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(str(run["created_at"]).replace("Z", "+00:00"))
    except (ValueError, KeyError, TypeError) as exc:
        raise ResearchQaIncidentError("original QA run time cannot be bound") from exc
    if (recorded.tzinfo is None or created.tzinfo is None
            or abs((recorded - created).total_seconds()) > 90):
        raise ResearchQaIncidentError("original QA run does not match dispatched task time")


def recover_incident(
    config: dict[str, Any], *, spec: dict[str, Any],
    api_get: Callable[[str], dict[str, Any]], current_sha: str,
) -> bool:
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or not SHA40.fullmatch(current_sha)
            or not SHA40.fullmatch(spec["producer_source_sha"])
            or not SHA40.fullmatch(spec["failed_qa_head_sha"])):
        return False
    by_id = {t["id"]: t for t in config.get("tasks", [])}
    task, predecessor = by_id.get(FIFTH), by_id.get(FOURTH)
    if not isinstance(task, dict) or not isinstance(predecessor, dict):
        return False
    if task.get("research_qa_incident_recovery") is not None:
        return False
    production = task.get("result_evidence")
    if (task.get("status") not in {"RUNNING", "TRIAGE", "BLOCKED"}
            or task.get("triage_mode") != "root_cause_first"
            or task.get("assigned_worker") not in {"architect-agent", None}
            or task.get("producer") != "research-agent"
            or task.get("verifier") != "qa-verifier-agent"
            or task.get("research_producer_lease_id") != spec["producer_lease_id"]
            or task.get("verification_evidence") is not None
            or not isinstance(production, dict)
            or production.get("executor") != "nexus-real-composite-backtest"
            or production.get("receipt_digest") != spec["producer_receipt_digest"]
            or production.get("source_sha") != spec["producer_source_sha"]
            or production.get("lease_id") != spec["producer_lease_id"]
            or production.get("independent_qa_complete") is not False
            or production.get("auto_demo_promotion") is not False
            or production.get("live_enabled") is not False
            or production.get("qualification_authority") is not False
            or not isinstance(task.get("external_wait_timeline"), list)):
        return False
    try:
        predecessor_binding = attested_predecessor(predecessor)
    except ValueError:
        return False
    if any(task.get(k) != predecessor_binding[k] for k in ANCESTRY):
        return False
    # A source/lease/attempt-bound old dispatch ID proves the exact older
    # rejected worker is part of this existing manager's task history.
    from agent_transport import dispatch_id_for
    old = deepcopy(task)
    old["status"] = "VERIFYING"
    old["assigned_worker"] = "qa-verifier-agent"
    old["lease_id"] = spec["failed_qa_lease_id"]
    if dispatch_id_for(old) != spec["failed_qa_dispatch_id"]:
        return False
    matches = [item for item in task["external_wait_timeline"]
               if isinstance(item, dict)
               and item.get("worker_id") == "qa-verifier-agent"
               and item.get("dispatch_id") == spec["failed_qa_dispatch_id"]]
    if len(matches) != 1:
        return False
    run_id = spec["failed_qa_run_id"]
    run = api_get(f"repos/{REPO}/actions/runs/{run_id}")
    jobs = api_get(f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100")
    _old_qa_run_fail_closed(run, jobs, spec, matches[0])
    former = {
        "abandoned_triage_lease_id": task.get("lease_id"),
        "abandoned_triage_dispatch_id": task.get("dispatch_id"),
        "original_rejected_qa_run_id": run_id,
        "original_rejected_qa_dispatch_id": spec["failed_qa_dispatch_id"],
        "original_producer_source_sha": spec["producer_source_sha"],
        "original_producer_receipt_digest": spec["producer_receipt_digest"],
        "original_producer_lease_id": spec["producer_lease_id"],
        "new_qa_lease_id": None,
        "reason": "verified_failed_source_epoch_new_independent_qa_only",
        "independent_qa_complete": False,
        "automatic_demo_promotion": False,
        "live_enabled": False,
    }
    # No old lease can complete the newly created independent QA lease.
    for field in (
        "assigned_worker", "lease_id", "leased_at", "heartbeat_at",
        "lease_expires_at", "dispatch_id", "dispatch_transport",
        "dispatched_at", "external_wait_state", "external_wait_started_at",
        "result_received_at",
    ):
        task[field] = None
    task["triage_mode"] = None
    task["required_output"] = None
    task["failure_class"] = None
    task["blocked_reason"] = None
    task["status"] = "BLOCKED"
    if not am.request_verification(config, task, am.utcnow()):
        # A missing eligible independent verifier must not promote or
        # dispatch anything. Preserve exact previous evidence and blocked status.
        task["blocked_reason"] = "incident_recovery_independent_qa_unavailable"
        return False
    former["new_qa_lease_id"] = task["lease_id"]
    task["research_qa_incident_recovery"] = former
    am.emit("verified_research_qa_epoch_retry_leased",
            task_id=FIFTH, failed_qa_run_id=run_id,
            new_qa_lease_id=task["lease_id"],
            producer_source_sha=spec["producer_source_sha"])
    return True
