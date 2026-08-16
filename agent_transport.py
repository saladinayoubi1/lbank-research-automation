from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any

import agent_manager as am

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")
EXECUTOR_WORKFLOW = "nexus-agent-executor.yml"
ARTIFACT_PREFIX = "nexus-agent-result-"


def _api(method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GitHub token missing")
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw.decode("utf-8")) if raw else None


def _repo() -> str:
    value = os.environ.get("GITHUB_REPOSITORY")
    if not value or "/" not in value:
        raise RuntimeError("GITHUB_REPOSITORY missing")
    return value


def transport_for(worker_id: str) -> str:
    if worker_id == "deepseek-bounded":
        return "deepseek"
    if worker_id == "windows-runner":
        return "windows"
    return "github-cloud"


def envelope_for(task: dict[str, Any]) -> dict[str, Any]:
    lease_id = task.get("lease_id")
    worker = task.get("assigned_worker")
    if not lease_id or not worker:
        raise ValueError("leased task missing lease_id/assigned_worker")
    if int(task.get("authority", 0)) >= 4:
        raise ValueError("L4 tasks may not be dispatched")
    return {
        "schema_version": 1,
        "task_id": task["id"],
        "lease_id": lease_id,
        "worker_id": worker,
        "transport": transport_for(worker),
        "phase": task.get("phase"),
        "gate": task.get("gate"),
        "title": task.get("title", ""),
        "required_capabilities": task.get("required_capabilities", []),
        "acceptance": task.get("acceptance", []),
        "authority": int(task.get("authority", 0)),
        "attempt": int(task.get("attempt", 0)),
    }


def dispatch_task(task: dict[str, Any], *, ref: str) -> None:
    env = envelope_for(task)
    encoded = base64.urlsafe_b64encode(json.dumps(env, sort_keys=True).encode("utf-8")).decode("ascii")
    repo = _repo()
    _api(
        "POST",
        f"https://api.github.com/repos/{repo}/actions/workflows/{EXECUTOR_WORKFLOW}/dispatches",
        {
            "ref": ref,
            "inputs": {
                "payload_b64": encoded,
                "lease_id": env["lease_id"],
                "transport": env["transport"],
            },
        },
    )
    now = am.utcnow()
    task["status"] = "RUNNING"
    task["dispatch_id"] = uuid.uuid4().hex
    task["dispatch_transport"] = env["transport"]
    task["dispatched_at"] = am.iso(now)
    task["heartbeat_at"] = am.iso(now)
    task["lease_expires_at"] = am.iso(now + am.timedelta(minutes=am.DEFAULT_LEASE_MINUTES))
    am.emit("task_dispatched", task_id=task["id"], worker=env["worker_id"], transport=env["transport"], lease_id=env["lease_id"])


def dispatch_pending(config: dict[str, Any], *, ref: str) -> int:
    count = 0
    for task in config.get("tasks", []):
        if task.get("status") != "LEASED" or task.get("dispatch_id"):
            continue
        dispatch_task(task, ref=ref)
        count += 1
    return count


def _artifact_json(artifact_id: int) -> dict[str, Any]:
    repo = _repo()
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        blob = resp.read()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = [n for n in zf.namelist() if n.endswith("result.json")]
        if len(names) != 1:
            raise RuntimeError("result artifact must contain exactly one result.json")
        return json.loads(zf.read(names[0]).decode("utf-8"))


def find_result(lease_id: str) -> dict[str, Any] | None:
    repo = _repo()
    name = f"{ARTIFACT_PREFIX}{lease_id}"
    payload = _api("GET", f"https://api.github.com/repos/{repo}/actions/artifacts?name={name}&per_page=10")
    artifacts = [a for a in (payload or {}).get("artifacts", []) if not a.get("expired") and a.get("name") == name]
    if not artifacts:
        return None
    artifacts.sort(key=lambda a: a.get("created_at", ""), reverse=True)
    return _artifact_json(int(artifacts[0]["id"]))


def ingest_result(config: dict[str, Any], task: dict[str, Any], result: dict[str, Any]) -> None:
    if result.get("schema_version") != 1:
        raise ValueError("unsupported result schema")
    if result.get("task_id") != task.get("id") or result.get("lease_id") != task.get("lease_id"):
        raise ValueError("stale or mismatched task result")
    if result.get("worker_id") != task.get("assigned_worker"):
        raise ValueError("result worker does not own lease")
    outcome = result.get("outcome")
    if outcome not in {"success", "failure"}:
        raise ValueError("invalid result outcome")
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("result evidence must be an object")
    am.record_result(config, task["id"], task["assigned_worker"], outcome, evidence)
    task["result_artifact_ingested"] = True
    task["result_received_at"] = am.iso()
    am.emit("task_result_ingested", task_id=task["id"], outcome=outcome, lease_id=task.get("lease_id"))


def poll_results(config: dict[str, Any]) -> int:
    count = 0
    for task in config.get("tasks", []):
        if task.get("status") != "RUNNING" or not task.get("dispatch_id"):
            continue
        lease_id = task.get("lease_id")
        if not lease_id:
            continue
        result = find_result(lease_id)
        if result is None:
            continue
        ingest_result(config, task, result)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS agent dispatch/result transport")
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", "main"))
    args = parser.parse_args()
    path = Path(args.runtime)
    config = json.loads(path.read_text(encoding="utf-8"))
    am.validate_config(config)
    am.enforce_owner_boundaries(config)
    ingested = poll_results(config)
    dispatched = dispatch_pending(config, ref=args.ref)
    am.atomic_json(path, config)
    am.atomic_json(Path(args.summary), am.summarize(config))
    print(json.dumps({"dispatched": dispatched, "ingested": ingested, "summary": am.summarize(config)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
