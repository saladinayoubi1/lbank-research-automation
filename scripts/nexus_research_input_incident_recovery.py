"""One reviewed Research #010 input recovery; never a generic numeric retry."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable

import agent_manager as am
from nexus_research_missions import ANCESTRY, NINTH, TENTH, attested_predecessor, validate_ancestry

REPO = "saladinayoubi1/lbank-research-automation"
SPEC = Path(".nexus/recovery/research-tenth-frontier-input-v1.json")
SCHEMA = "nexus.research-input-incident-recovery.v1"
EXPECTED_KEYS = {
    "schema", "task_id", "failed_source_sha", "failed_run_id", "failed_lease_id",
    "failed_dispatch_id", "failed_artifact_id", "failed_artifact_digest",
    "first_failed_lease_id", "fix_commit_sha", "fix_prepare_blob_sha",
    "predecessor", "reason", "automatic_demo_promotion", "live_enabled",
}
FAILURE = {
    "executor": "nexus-real-composite-backtest",
    "failure_class": "verified_research_execution_failed",
    "reason": "required immutable input or evidence is not a regular file",
    "auto_demo_promotion": False, "live_enabled": False,
    "qualification_authority": False,
}


def load_spec(path: Path = SPEC) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("reviewed Research input recovery contract absent or unsafe")
    spec = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(spec, dict) or set(spec) != EXPECTED_KEYS
        or spec.get("schema") != SCHEMA or spec.get("task_id") != TENTH
        or any(not re.fullmatch(r"[0-9a-f]{40}", str(spec.get(k, "")))
               for k in ("failed_source_sha", "fix_commit_sha", "fix_prepare_blob_sha"))
        or spec["failed_source_sha"] == spec["fix_commit_sha"]
        or not re.fullmatch(r"[0-9a-f]{64}", str(spec.get("failed_artifact_digest", "")))
        or not re.fullmatch(r"[0-9a-f]{32}", str(spec.get("failed_dispatch_id", "")))
        or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,160}", str(spec.get(k, "")))
               for k in ("failed_lease_id", "first_failed_lease_id"))
        or any(type(spec.get(k)) is not int or spec[k] < 1
               for k in ("failed_run_id", "failed_artifact_id"))
        or not isinstance(spec.get("reason"), str) or not 30 <= len(spec["reason"]) <= 500
        or spec.get("automatic_demo_promotion") is not False
        or spec.get("live_enabled") is not False
    ):
        raise ValueError("reviewed Research input recovery contract invalid")
    validate_ancestry(spec["predecessor"])
    return spec


def _verify_source_and_failure(api_get, spec, current_sha, event) -> None:
    run = api_get(f"repos/{REPO}/actions/runs/{spec['failed_run_id']}")
    if (
        run.get("id") != spec["failed_run_id"] or run.get("name") != "NEXUS Runtime Worker"
        or run.get("path") != ".github/workflows/nexus-runtime-worker.yml"
        or run.get("head_branch") != "main" or run.get("head_sha") != spec["failed_source_sha"]
        or run.get("status") != "completed" or run.get("event") != "workflow_dispatch"
        or run.get("conclusion") != "success"  # Outer success still contains a failed result.
        or (run.get("repository") or {}).get("full_name") != REPO
        or (run.get("head_repository") or {}).get("full_name") != REPO
        or (run.get("actor") or {}).get("login") != "github-actions[bot]"
    ):
        raise ValueError("original failed producer run identity differs")
    created = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00"))
    dispatched = datetime.fromisoformat(event["started_at"].replace("Z", "+00:00"))
    if created.tzinfo is None or dispatched.tzinfo is None or abs((created - dispatched).total_seconds()) > 90:
        raise ValueError("original failed producer time differs")
    artifacts = api_get(f"repos/{REPO}/actions/runs/{spec['failed_run_id']}/artifacts?per_page=100")
    matches = [a for a in artifacts.get("artifacts", []) if a.get("id") == spec["failed_artifact_id"]]
    if (len(matches) != 1 or matches[0].get("expired") is not False
            or matches[0].get("name") != "nexus-agent-result-" + spec["failed_lease_id"]
            or matches[0].get("digest") != "sha256:" + spec["failed_artifact_digest"]
            or (matches[0].get("workflow_run") or {}).get("head_sha") != spec["failed_source_sha"]):
        raise ValueError("original failed producer artifact differs")
    compare = api_get(f"repos/{REPO}/compare/{spec['fix_commit_sha']}...{current_sha}")
    if (compare.get("status") not in {"ahead", "identical"}
            or (compare.get("base_commit") or {}).get("sha") != spec["fix_commit_sha"]
            or (compare.get("merge_base_commit") or {}).get("sha") != spec["fix_commit_sha"]):
        raise ValueError("current main does not contain the reviewed preparation fix")
    preparation = api_get(f"repos/{REPO}/contents/nexus_agent_research_prepare.py?ref={current_sha}")
    if preparation.get("type") != "file" or preparation.get("sha") != spec["fix_prepare_blob_sha"]:
        raise ValueError("reviewed preparation fix changed after review")


def recover_incident(
    config: dict[str, Any], *, spec: dict[str, Any],
    api_get: Callable[[str], dict[str, Any]], current_sha: str,
) -> bool:
    if (os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_REF") != "refs/heads/main"
            or os.environ.get("GITHUB_SHA") != current_sha
            or not re.fullmatch(r"[0-9a-f]{40}", current_sha)):
        return False
    tasks = {t.get("id"): t for t in config.get("tasks", [])}
    task, prior = tasks.get(TENTH), tasks.get(NINTH)
    if not isinstance(task, dict) or not isinstance(prior, dict):
        return False
    race = task.get("research_cache_race_evidence") or {}
    triage = task.get("triage_evidence") or {}
    if not isinstance(race, dict) or not isinstance(triage, dict):
        return False
    if (task.get("research_input_incident_recovery") is not None
            or task.get("status") not in {"TRIAGE", "RUNNING", "BLOCKED"}
            or task.get("triage_mode") != "root_cause_first"
            or task.get("assigned_worker") not in {None, "architect-agent"}
            or (task.get("status") == "BLOCKED" and task.get("blocked_reason") != am.RESEARCH_RCA_BLOCK_REASON)
            or task.get("producer") != "research-agent" or task.get("verifier") is not None
            or task.get("phase") != 7 or task.get("authority") != 2
            or task.get("attempt") != 2 or task.get("research_cache_recovery_count") != 1
            or task.get("failure_class") != FAILURE["failure_class"]
            or task.get("failure_evidence") != FAILURE
            or task.get("result_evidence") is not None or task.get("verification_evidence") is not None
            or task.get("research_producer_lease_id") is not None
            or race.get("first_failed_lease_id") != spec["first_failed_lease_id"]
            or race.get("first_failure") != FAILURE
            or triage.get("preserved_original_failure") is not True
            or triage.get("worker_id") != "architect-agent"
            or triage.get("evidence") != {
                **{k: v for k, v in FAILURE.items() if k not in {"reason", "failure_class"}},
                "failure_class": "research_lease_worker_phase_or_transport_mismatch",
            }):
        return False
    try:
        if (attested_predecessor(prior) != spec["predecessor"]
                or {k: task.get(k) for k in ANCESTRY} != spec["predecessor"]):
            return False
        from agent_transport import dispatch_id_for
        failed = {**task, "assigned_worker": "research-agent", "lease_id": spec["failed_lease_id"]}
        if dispatch_id_for(failed) != spec["failed_dispatch_id"]:
            return False
        matches = [e for e in task.get("external_wait_timeline", [])
                   if e.get("dispatch_id") == spec["failed_dispatch_id"]
                   and e.get("worker_id") == "research-agent" and e.get("transport") == "github-cloud"
                   and e.get("from_status") == "LEASED" and e.get("outcome") == "failure"]
        if len(matches) != 1:
            return False
        _verify_source_and_failure(api_get, spec, current_sha, matches[0])
    except (RuntimeError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        am.emit("research_input_recovery_proof_unavailable", task_id=TENTH, error=type(exc).__name__)
        return False
    task["research_input_incident_recovery"] = {
        "schema": SCHEMA, "failed_run_id": spec["failed_run_id"],
        "failed_lease_id": spec["failed_lease_id"], "reviewed_fix_sha": spec["fix_commit_sha"],
        "recovery_source_sha": current_sha, "prior_attempt": task["attempt"],
        "abandoned_triage_lease_id": task.get("lease_id"),
        "abandoned_triage_dispatch_id": task.get("dispatch_id"),
        "original_failure": deepcopy(task["failure_evidence"]),
        "independent_qa_complete": False, "automatic_demo_promotion": False, "live_enabled": False,
    }
    for field in (
        "assigned_worker", "verifier", "lease_id", "leased_at", "heartbeat_at", "lease_expires_at",
        "dispatch_id", "dispatch_transport", "dispatched_at", "external_wait_state",
        "external_wait_started_at", "result_received_at", "triage_mode", "required_output", "blocked_reason",
    ):
        task[field] = None
    task["result_artifact_ingested"] = False
    task["status"] = "PENDING"  # Ordinary dependency, input gate and Research routing create the lease.
    am.emit("reviewed_research_input_incident_requeued", task_id=TENTH,
            failed_run_id=spec["failed_run_id"], recovery_source_sha=current_sha)
    return True
