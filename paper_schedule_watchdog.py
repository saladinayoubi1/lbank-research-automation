from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = "saladinayoubi1/lbank-research-automation"
WORKFLOW = "nexus_persistent_paper_trading_loop.yml"
DEFAULT_BRANCH = "main"
DEFAULT_STALE_MINUTES = 45
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}
UNSTARTED_STATUSES = {"queued", "waiting", "pending", "requested"}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def api_json(path: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "nexus-paper-schedule-watchdog",
    }
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}", headers=headers
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def get_workflow_runs() -> list[dict[str, Any]]:
    payload = api_json(
        f"actions/workflows/{WORKFLOW}/runs?branch={DEFAULT_BRANCH}&per_page=5"
    )
    return list(payload.get("workflow_runs", []))


def latest_identity(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None
    run = runs[0]
    return {
        "id": run.get("id"),
        "status": run.get("status"),
        "conclusion": run.get("conclusion"),
        "created_at": run.get("created_at"),
        "head_sha": run.get("head_sha"),
        "event": run.get("event"),
        "html_url": run.get("html_url"),
    }


def run_age_minutes(run: dict[str, Any], *, now: datetime) -> float | None:
    created_raw = run.get("created_at")
    if not isinstance(created_raw, str) or not created_raw:
        return None
    try:
        created_at = parse_utc(created_raw)
    except (TypeError, ValueError):
        return None
    return max(
        0.0,
        (now.astimezone(timezone.utc) - created_at).total_seconds() / 60.0,
    )


def evaluate_runs(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    stale_minutes: int,
    current_sha: str | None = None,
) -> dict[str, Any]:
    latest = latest_identity(runs)
    if latest is None:
        return {
            "decision": "DISPATCH_REQUIRED_NO_HISTORY",
            "latest": None,
            "age_minutes": None,
        }

    created_raw = latest.get("created_at")
    if not isinstance(created_raw, str) or not created_raw:
        return {
            "decision": "FAIL_CLOSED_MISSING_CREATED_AT",
            "latest": latest,
            "age_minutes": None,
        }
    try:
        created_at = parse_utc(created_raw)
    except (TypeError, ValueError):
        return {
            "decision": "FAIL_CLOSED_INVALID_CREATED_AT",
            "latest": latest,
            "age_minutes": None,
        }

    age_minutes = max(
        0.0,
        (now.astimezone(timezone.utc) - created_at).total_seconds() / 60.0,
    )
    rounded_age = round(age_minutes, 3)
    status = str(latest.get("status") or "").lower()
    conclusion = str(latest.get("conclusion") or "").lower()

    if status in ACTIVE_STATUSES:
        latest_sha = str(latest.get("head_sha") or "")
        if (
            status in UNSTARTED_STATUSES
            and current_sha
            and latest_sha
            and latest_sha != current_sha
            and age_minutes > stale_minutes
        ):
            return {
                "decision": "RECOVER_STALE_NONCURRENT_ACTIVE",
                "latest": latest,
                "age_minutes": rounded_age,
            }
        return {
            "decision": "HEALTHY_ACTIVE_RUN",
            "latest": latest,
            "age_minutes": rounded_age,
        }

    if status != "completed":
        return {
            "decision": "FAIL_CLOSED_UNKNOWN_STATUS",
            "latest": latest,
            "age_minutes": rounded_age,
        }
    if conclusion != "success":
        return {
            "decision": "FAIL_CLOSED_LAST_RUN_UNSUCCESSFUL",
            "latest": latest,
            "age_minutes": rounded_age,
        }
    if age_minutes <= stale_minutes:
        return {
            "decision": "HEALTHY_RECENT_SUCCESS",
            "latest": latest,
            "age_minutes": rounded_age,
        }
    return {
        "decision": "DISPATCH_REQUIRED_STALE_SUCCESS",
        "latest": latest,
        "age_minutes": rounded_age,
    }


def stale_predecessor_candidates(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    stale_minutes: int,
    current_sha: str | None,
) -> list[dict[str, Any]]:
    """Return only stale unstarted predecessors behind a newer unstarted run.

    The newest workflow run must itself still be unstarted. Its SHA may be one
    or more main commits behind the coordinator's current SHA because main can
    advance after the Paper run was dispatched. We never cancel that newest run;
    only older stale unstarted runs can be selected as blockers.
    """
    if len(runs) < 2:
        return []

    newest = runs[0]
    newest_status = str(newest.get("status") or "").lower()
    newest_id = newest.get("id")
    if newest_status not in UNSTARTED_STATUSES or not isinstance(newest_id, int):
        return []

    candidates: list[dict[str, Any]] = []
    for run in runs[1:]:
        status = str(run.get("status") or "").lower()
        run_id = run.get("id")
        age_minutes = run_age_minutes(run, now=now)
        if status not in UNSTARTED_STATUSES:
            continue
        if not isinstance(run_id, int) or run_id == newest_id or age_minutes is None:
            continue
        if age_minutes <= stale_minutes:
            continue
        candidates.append(
            {
                "id": run_id,
                "status": status,
                "head_sha": run.get("head_sha"),
                "created_at": run.get("created_at"),
                "age_minutes": round(age_minutes, 3),
                "html_url": run.get("html_url"),
                "newest_run_id": newest_id,
                "newest_head_sha": newest.get("head_sha"),
                "coordinator_current_sha": current_sha,
            }
        )
    return candidates


def paper_run_safe_to_cancel(run_id: int) -> tuple[bool, str]:
    payload = api_json(f"actions/runs/{run_id}/jobs?filter=latest&per_page=100")
    jobs = list(payload.get("jobs", []))
    if not jobs:
        return True, "workflow_pending_before_job_creation"

    paper_jobs = [job for job in jobs if job.get("name") == "paper-loop"]
    if len(paper_jobs) != 1:
        return False, f"paper_loop_job_count={len(paper_jobs)}"

    paper_job = paper_jobs[0]
    status = str(paper_job.get("status") or "").lower()
    steps = paper_job.get("steps")
    if status not in UNSTARTED_STATUSES:
        return False, f"paper_loop_status={status or 'missing'}"
    if steps not in (None, []):
        return False, "paper_loop_has_steps"
    return True, f"paper_loop_unstarted_status={status}"


def run_gh(args: list[str]) -> tuple[bool, str]:
    gh = shutil.which("gh")
    if not gh:
        return False, "gh_cli_unavailable"
    completed = subprocess.run(
        [gh, *args],
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    detail = (completed.stderr or completed.stdout).strip()
    return completed.returncode == 0, detail


def cancel_workflow_run(run_id: int) -> tuple[bool, str]:
    return run_gh(
        [
            "api",
            "--method",
            "POST",
            f"repos/{REPO}/actions/runs/{run_id}/cancel",
        ]
    )


def dispatch_workflow() -> tuple[bool, str]:
    return run_gh(
        [
            "workflow",
            "run",
            WORKFLOW,
            "--repo",
            REPO,
            "--ref",
            DEFAULT_BRANCH,
        ]
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temp, path)


def requires_write(decision: str) -> bool:
    return decision.startswith("DISPATCH_REQUIRED_") or decision == "RECOVER_STALE_NONCURRENT_ACTIVE"


def watch_once(*, stale_minutes: int = DEFAULT_STALE_MINUTES) -> dict[str, Any]:
    now = utcnow()
    current_sha = os.environ.get("GITHUB_SHA") or None
    current_ref = os.environ.get("GITHUB_REF_NAME")
    first_runs = get_workflow_runs()
    first = evaluate_runs(
        first_runs,
        now=now,
        stale_minutes=stale_minutes,
        current_sha=current_sha,
    )
    evidence: dict[str, Any] = {
        "schema_version": 4,
        "generated_at_utc": now.isoformat(),
        "repo": REPO,
        "workflow": WORKFLOW,
        "branch": DEFAULT_BRANCH,
        "current_sha": current_sha,
        "stale_minutes": stale_minutes,
        "initial": first,
        "decision": first["decision"],
        "cancel_attempted": False,
        "cancel_ok": False,
        "cancel_detail": None,
        "dispatch_attempted": False,
        "dispatch_ok": False,
        "dispatch_detail": None,
    }

    predecessors = stale_predecessor_candidates(
        first_runs,
        now=now,
        stale_minutes=stale_minutes,
        current_sha=current_sha,
    )
    if predecessors:
        evidence["stale_predecessor_candidates"] = predecessors
        if current_ref and current_ref != DEFAULT_BRANCH:
            evidence["decision"] = "FAIL_CLOSED_NON_DEFAULT_REF"
            return evidence

        safety: list[dict[str, Any]] = []
        all_safe = True
        for candidate in predecessors:
            safe, detail = paper_run_safe_to_cancel(candidate["id"])
            safety.append(
                {
                    "run_id": candidate["id"],
                    "safe": safe,
                    "detail": detail,
                }
            )
            all_safe = all_safe and safe
        evidence["stale_predecessor_safety"] = safety
        if not all_safe:
            evidence["decision"] = "FAIL_CLOSED_STALE_PREDECESSOR_NOT_SAFE_TO_CANCEL"
            return evidence

        cancellations: list[dict[str, Any]] = []
        evidence["cancel_attempted"] = True
        for candidate in predecessors:
            cancel_ok, cancel_detail = cancel_workflow_run(candidate["id"])
            cancellations.append(
                {
                    "run_id": candidate["id"],
                    "ok": cancel_ok,
                    "detail": cancel_detail,
                }
            )
            if not cancel_ok:
                evidence["cancel_ok"] = False
                evidence["cancel_detail"] = cancellations
                evidence["decision"] = "STALE_PREDECESSOR_CANCEL_FAILED"
                return evidence
        evidence["cancel_ok"] = True
        evidence["cancel_detail"] = cancellations

        refreshed_runs = get_workflow_runs()
        refreshed = evaluate_runs(
            refreshed_runs,
            now=utcnow(),
            stale_minutes=stale_minutes,
            current_sha=current_sha,
        )
        evidence["after_predecessor_recovery"] = refreshed
        if refreshed["decision"] == "HEALTHY_ACTIVE_RUN":
            evidence["decision"] = "STALE_PREDECESSORS_CANCELLED_NEWEST_ACTIVE"
            return evidence
        first_runs = refreshed_runs
        first = refreshed
        evidence["decision"] = first["decision"]

    if not requires_write(str(first["decision"])):
        return evidence

    # Re-read authoritative workflow history immediately before any write. This
    # prevents two coordinator iterations from dispatching duplicate Paper runs
    # or cancelling a run whose state changed after the first observation.
    second_runs = get_workflow_runs()
    second = evaluate_runs(
        second_runs,
        now=utcnow(),
        stale_minutes=stale_minutes,
        current_sha=current_sha,
    )
    evidence["authoritative_recheck"] = second
    if not requires_write(str(second["decision"])):
        evidence["decision"] = "WRITE_SUPPRESSED_AFTER_RECHECK"
        return evidence

    if current_ref and current_ref != DEFAULT_BRANCH:
        evidence["decision"] = "FAIL_CLOSED_NON_DEFAULT_REF"
        return evidence

    if second["decision"] == "RECOVER_STALE_NONCURRENT_ACTIVE":
        latest = second.get("latest") or {}
        run_id = latest.get("id")
        if not isinstance(run_id, int):
            evidence["decision"] = "FAIL_CLOSED_STALE_ACTIVE_MISSING_RUN_ID"
            return evidence

        safe, detail = paper_run_safe_to_cancel(run_id)
        evidence["cancel_safety"] = {"safe": safe, "detail": detail, "run_id": run_id}
        if not safe:
            evidence["decision"] = "FAIL_CLOSED_STALE_ACTIVE_NOT_SAFE_TO_CANCEL"
            return evidence

        cancel_ok, cancel_detail = cancel_workflow_run(run_id)
        evidence["cancel_attempted"] = True
        evidence["cancel_ok"] = cancel_ok
        evidence["cancel_detail"] = cancel_detail
        if not cancel_ok:
            evidence["decision"] = "STALE_ACTIVE_CANCEL_FAILED"
            return evidence

    ok, detail = dispatch_workflow()
    evidence["dispatch_attempted"] = True
    evidence["dispatch_ok"] = ok
    evidence["dispatch_detail"] = detail
    if ok and evidence["cancel_attempted"]:
        evidence["decision"] = "STALE_ACTIVE_CANCELLED_AND_DISPATCHED"
    else:
        evidence["decision"] = "DISPATCHED" if ok else "DISPATCH_FAILED"
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed watchdog for the persistent NEXUS Paper schedule."
    )
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/agent_coordination/paper_schedule_watchdog.json"),
    )
    args = parser.parse_args()
    stale_minutes = max(30, args.stale_minutes)
    try:
        evidence = watch_once(stale_minutes=stale_minutes)
    except Exception as exc:  # fail closed while preserving coordinator evidence
        evidence = {
            "schema_version": 4,
            "generated_at_utc": utcnow().isoformat(),
            "repo": REPO,
            "workflow": WORKFLOW,
            "branch": DEFAULT_BRANCH,
            "decision": "FAIL_CLOSED_WATCHDOG_EXCEPTION",
            "error_class": type(exc).__name__,
            "error_message": str(exc),
            "cancel_attempted": False,
            "cancel_ok": False,
            "dispatch_attempted": False,
            "dispatch_ok": False,
        }
    write_json(args.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
