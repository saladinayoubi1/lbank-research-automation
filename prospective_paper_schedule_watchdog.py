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
WORKFLOW = "bybit_prospective_paper_forward_v1.yml"
DEFAULT_BRANCH = "main"
DEFAULT_STALE_MINUTES = 150
ACTIVE_STATUSES = {"queued", "in_progress", "waiting", "pending", "requested"}


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
        "User-Agent": "nexus-prospective-paper-schedule-watchdog",
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


def evaluate_runs(
    runs: list[dict[str, Any]],
    *,
    now: datetime,
    stale_minutes: int,
) -> dict[str, Any]:
    latest = latest_identity(runs)
    if latest is None:
        return {
            "decision": "DISPATCH_REQUIRED_NO_HISTORY",
            "latest": None,
            "age_minutes": None,
        }

    status = str(latest.get("status") or "").lower()
    conclusion = str(latest.get("conclusion") or "").lower()
    if status in ACTIVE_STATUSES:
        return {
            "decision": "HEALTHY_ACTIVE_RUN",
            "latest": latest,
            "age_minutes": None,
        }
    if status != "completed":
        return {
            "decision": "FAIL_CLOSED_UNKNOWN_STATUS",
            "latest": latest,
            "age_minutes": None,
        }
    if conclusion != "success":
        return {
            "decision": "FAIL_CLOSED_LAST_RUN_UNSUCCESSFUL",
            "latest": latest,
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


def requires_dispatch(decision: str) -> bool:
    return decision in {
        "DISPATCH_REQUIRED_NO_HISTORY",
        "DISPATCH_REQUIRED_STALE_SUCCESS",
    }


def watch_once(*, stale_minutes: int = DEFAULT_STALE_MINUTES) -> dict[str, Any]:
    now = utcnow()
    first = evaluate_runs(
        get_workflow_runs(),
        now=now,
        stale_minutes=stale_minutes,
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "generated_at_utc": now.isoformat(),
        "repo": REPO,
        "workflow": WORKFLOW,
        "branch": DEFAULT_BRANCH,
        "current_sha": os.environ.get("GITHUB_SHA") or None,
        "stale_minutes": stale_minutes,
        "paper_only": True,
        "live_trading_authority": False,
        "initial": first,
        "decision": first["decision"],
        "dispatch_attempted": False,
        "dispatch_ok": False,
        "dispatch_detail": None,
    }
    if not requires_dispatch(str(first["decision"])):
        return evidence

    if os.environ.get("GITHUB_REF_NAME") != DEFAULT_BRANCH:
        evidence["decision"] = "FAIL_CLOSED_NON_DEFAULT_REF"
        return evidence

    # Re-read authoritative history immediately before the only write. A run
    # created between reads suppresses dispatch, preventing duplicate recovery.
    second = evaluate_runs(
        get_workflow_runs(),
        now=utcnow(),
        stale_minutes=stale_minutes,
    )
    evidence["authoritative_recheck"] = second
    if not requires_dispatch(str(second["decision"])):
        evidence["decision"] = "DISPATCH_SUPPRESSED_AFTER_RECHECK"
        return evidence

    ok, detail = dispatch_workflow()
    evidence["dispatch_attempted"] = True
    evidence["dispatch_ok"] = ok
    evidence["dispatch_detail"] = detail
    evidence["decision"] = "DISPATCHED" if ok else "DISPATCH_FAILED"
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail-closed watchdog for the prospective Bybit Paper schedule."
    )
    parser.add_argument("--stale-minutes", type=int, default=DEFAULT_STALE_MINUTES)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "data/agent_coordination/prospective_paper_schedule_watchdog.json"
        ),
    )
    args = parser.parse_args()
    stale_minutes = max(DEFAULT_STALE_MINUTES, args.stale_minutes)
    try:
        evidence = watch_once(stale_minutes=stale_minutes)
    except Exception as exc:  # fail closed while preserving coordinator evidence
        evidence = {
            "schema_version": 1,
            "generated_at_utc": utcnow().isoformat(),
            "repo": REPO,
            "workflow": WORKFLOW,
            "branch": DEFAULT_BRANCH,
            "paper_only": True,
            "live_trading_authority": False,
            "decision": "FAIL_CLOSED_WATCHDOG_EXCEPTION",
            "error_class": type(exc).__name__,
            "error_message": str(exc),
            "dispatch_attempted": False,
            "dispatch_ok": False,
        }
    write_json(args.output, evidence)
    print(json.dumps(evidence, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
