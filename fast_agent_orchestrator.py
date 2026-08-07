from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = "saladinayoubi1/lbank-research-automation"
STATE_DIR = Path("data/agent_coordination")
STATE_FILE = STATE_DIR / "status.json"
EVENT_FILE = STATE_DIR / "events.jsonl"
HEARTBEAT_FILE = STATE_DIR / "local_heartbeat.json"
DEFAULT_POLL_SECONDS = 30


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def event(kind: str, **fields: Any) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"at": utcnow(), "kind": kind, **fields}
    with EVENT_FILE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(cmd: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout, check=False)


def gh_available() -> bool:
    return shutil.which("gh") is not None


def github_api_json(path: str) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "nexus-fast-agent-orchestrator"},
    )
    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def get_runs() -> list[dict[str, Any]]:
    if gh_available():
        cp = run([
            "gh", "run", "list", "--repo", REPO, "--limit", "20",
            "--json", "databaseId,name,status,conclusion,headSha,createdAt,updatedAt,event,url",
        ])
        if cp.returncode == 0:
            return json.loads(cp.stdout or "[]")
    data = github_api_json("actions/runs?per_page=20")
    result = []
    for item in data.get("workflow_runs", []):
        result.append({
            "databaseId": item.get("id"),
            "name": item.get("name"),
            "status": item.get("status"),
            "conclusion": item.get("conclusion"),
            "headSha": item.get("head_sha"),
            "createdAt": item.get("created_at"),
            "updatedAt": item.get("updated_at"),
            "event": item.get("event"),
            "url": item.get("html_url"),
        })
    return result


def rerun_failed(run_id: int) -> tuple[bool, str]:
    if not gh_available():
        return False, "gh CLI unavailable; read-only detection only"
    cp = run(["gh", "run", "rerun", str(run_id), "--failed", "--repo", REPO])
    return cp.returncode == 0, (cp.stderr or cp.stdout).strip()


def classify(run_info: dict[str, Any]) -> str:
    status = (run_info.get("status") or "").lower()
    conclusion = (run_info.get("conclusion") or "").lower()
    if status in {"waiting", "pending", "requested"}:
        return "WAITING"
    if status in {"queued", "in_progress"}:
        return "RUNNING"
    if conclusion == "success":
        return "DONE"
    if conclusion in {"failure", "timed_out", "startup_failure"}:
        return "FAILED"
    if conclusion == "action_required":
        return "WAITING"
    if conclusion in {"cancelled", "stale"}:
        return "BLOCKED"
    return "UNKNOWN"


def newest_by_name(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for info in runs:
        name = info.get("name") or "unknown"
        if name not in latest:
            latest[name] = info
    return latest


def inspect_once(previous: dict[str, Any], auto_retry: bool) -> dict[str, Any]:
    checked_at = utcnow()
    try:
        runs = get_runs()
        online = True
        network_error = None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        runs = []
        online = False
        network_error = f"{type(exc).__name__}: {exc}"

    latest = newest_by_name(runs)
    workflows: dict[str, Any] = {}
    prev_workflows = previous.get("workflows", {}) if isinstance(previous, dict) else {}

    for name, info in latest.items():
        state = classify(info)
        old = prev_workflows.get(name, {})
        old_state = old.get("state")
        run_id = info.get("databaseId")
        retry = {"attempted": False, "ok": False, "detail": None}

        if state != old_state:
            event("state_change", workflow=name, old=old_state, new=state, run_id=run_id)

        already_retried_id = old.get("last_auto_retry_run_id")
        if auto_retry and state == "FAILED" and run_id and already_retried_id != run_id:
            ok, detail = rerun_failed(int(run_id))
            retry = {"attempted": True, "ok": ok, "detail": detail}
            event("auto_retry", workflow=name, run_id=run_id, ok=ok, detail=detail)

        workflows[name] = {
            "state": state,
            "run_id": run_id,
            "conclusion": info.get("conclusion"),
            "status": info.get("status"),
            "head_sha": info.get("headSha"),
            "updated_at": info.get("updatedAt"),
            "url": info.get("url"),
            "last_auto_retry_run_id": run_id if retry["attempted"] else old.get("last_auto_retry_run_id"),
            "auto_retry": retry,
        }

    summary_states = ["RUNNING", "WAITING", "DONE", "FAILED", "BLOCKED", "UNKNOWN"]
    heartbeat = {
        "schema_version": 1,
        "generated_at": checked_at,
        "pid": os.getpid(),
        "local_process_alive": True,
        "internet_reachable": online,
        "network_error": network_error,
        "gh_cli_available": gh_available(),
    }
    atomic_json(HEARTBEAT_FILE, heartbeat)

    return {
        "schema_version": 2,
        "generated_at": checked_at,
        "repo": REPO,
        "poll_seconds": previous.get("poll_seconds", DEFAULT_POLL_SECONDS) if isinstance(previous, dict) else DEFAULT_POLL_SECONDS,
        "local_node": heartbeat,
        "workflows": workflows,
        "summary": {
            key: sum(1 for value in workflows.values() if value["state"] == key)
            for key in summary_states
        },
    }


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fast local coordinator for NEXUS GitHub jobs.")
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--no-auto-retry", action="store_true")
    args = parser.parse_args()
    poll_seconds = max(15, args.poll_seconds)

    while True:
        previous = load_state()
        previous["poll_seconds"] = poll_seconds
        current = inspect_once(previous, auto_retry=not args.no_auto_retry)
        current["poll_seconds"] = poll_seconds
        atomic_json(STATE_FILE, current)
        print(json.dumps(current["summary"], ensure_ascii=False), flush=True)
        if args.once:
            return 0
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
