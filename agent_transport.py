from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import agent_manager as am

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")
EXECUTOR_WORKFLOW = "nexus-runtime-worker.yml"
ARTIFACT_PREFIX = "nexus-agent-result-"
RESULT_KEYS = {
    "schema_version", "task_id", "lease_id", "correlation_id", "dispatch_id",
    "worker_id", "transport", "outcome", "evidence",
}
DISPATCHABLE = {"LEASED", "RUNNING", "VERIFYING"}
RESULT_WAITING = {"RUNNING", "VERIFYING"}


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


def _bounded_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 160:
        raise ValueError(f"{field} must be a non-empty bounded string")
    return value


def _stable_id(kind: str, *parts: Any) -> str:
    raw = "|".join([kind, *(str(part) for part in parts)]).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


def correlation_for(task: dict[str, Any]) -> str:
    """Stable task-lifecycle correlation ID preserved across leases and verification."""
    return _stable_id("nexus-agent-correlation-v1", task.get("phase"), task.get("gate"), task.get("id"))


def dispatch_id_for(task: dict[str, Any]) -> str:
    """Lease-scoped dispatch ID; a retry/new lease necessarily gets a different identity."""
    return _stable_id(
        "nexus-agent-dispatch-v1",
        correlation_for(task),
        task.get("lease_id"),
        task.get("assigned_worker"),
        int(task.get("attempt", 0)),
    )


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
    _bounded_id(str(task.get("id", "")), "task_id")
    _bounded_id(lease_id, "lease_id")
    _bounded_id(worker, "worker_id")
    if int(task.get("authority", 0)) >= 4:
        raise ValueError("L4 tasks may not be dispatched")
    return {
        "schema_version": 2,
        "task_id": task["id"],
        "lease_id": lease_id,
        "correlation_id": correlation_for(task),
        "dispatch_id": dispatch_id_for(task),
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
    prior_status = task.get("status")
    if prior_status not in DISPATCHABLE:
        raise ValueError("task is not in a dispatchable lease state")
    env = envelope_for(task)
    encoded = base64.urlsafe_b64encode(json.dumps(env, sort_keys=True).encode("utf-8")).decode("ascii")
    repo = _repo()
    _api(
        "POST",
        f"https://api.github.com/repos/{repo}/actions/workflows/{EXECUTOR_WORKFLOW}/dispatches",
        {"ref": ref, "inputs": {"payload_b64": encoded, "lease_id": env["lease_id"], "transport": env["transport"]}},
    )
    now = am.utcnow()
    if prior_status == "LEASED":
        task["status"] = "RUNNING"
    # VERIFYING must remain VERIFYING so a successful verifier result closes the task.
    # RUNNING is retained for root-cause-analysis leases.
    task["correlation_id"] = env["correlation_id"]
    task["dispatch_id"] = env["dispatch_id"]
    task["dispatch_transport"] = env["transport"]
    task["dispatched_at"] = am.iso(now)
    task["heartbeat_at"] = am.iso(now)
    task["lease_expires_at"] = am.iso(now + am.timedelta(minutes=am.DEFAULT_LEASE_MINUTES))
    am.emit(
        "task_dispatched",
        task_id=task["id"],
        worker=env["worker_id"],
        transport=env["transport"],
        lease_id=env["lease_id"],
        correlation_id=env["correlation_id"],
        dispatch_id=env["dispatch_id"],
        lease_status=prior_status,
    )


def dispatch_pending(config: dict[str, Any], *, ref: str) -> int:
    count = 0
    for task in config.get("tasks", []):
        if task.get("status") not in DISPATCHABLE or not task.get("lease_id") or not task.get("assigned_worker"):
            continue
        expected_dispatch = dispatch_id_for(task)
        if task.get("dispatch_id") == expected_dispatch:
            continue
        # A new lease (retry, verifier, or RCA analyst) supersedes any old dispatch identity.
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
    if not isinstance(result, dict) or set(result) != RESULT_KEYS:
        raise ValueError("result schema mismatch")
    if result.get("schema_version") != 2:
        raise ValueError("unsupported result schema")
    if result.get("task_id") != task.get("id") or result.get("lease_id") != task.get("lease_id"):
        raise ValueError("stale or mismatched task result")
    expected_correlation = task.get("correlation_id") or correlation_for(task)
    expected_dispatch = dispatch_id_for(task)
    if task.get("dispatch_id") != expected_dispatch:
        raise ValueError("task dispatch identity is stale for current lease")
    if result.get("correlation_id") != expected_correlation:
        raise ValueError("result correlation does not match task lifecycle")
    if result.get("dispatch_id") != expected_dispatch:
        raise ValueError("result dispatch identity does not match current lease")
    if result.get("worker_id") != task.get("assigned_worker"):
        raise ValueError("result worker does not own lease")
    expected_transport = task.get("dispatch_transport") or transport_for(str(task.get("assigned_worker")))
    if result.get("transport") != expected_transport:
        raise ValueError("result transport does not match dispatched route")
    outcome = result.get("outcome")
    if outcome not in {"success", "failure"}:
        raise ValueError("invalid result outcome")
    evidence = result.get("evidence")
    if not isinstance(evidence, dict):
        raise ValueError("result evidence must be an object")
    completed_lease_id = task.get("lease_id")
    completed_dispatch_id = expected_dispatch
    am.record_result(config, task["id"], task["assigned_worker"], outcome, evidence)
    task["result_artifact_ingested"] = True
    task["result_received_at"] = am.iso()
    am.emit(
        "task_result_ingested",
        task_id=task["id"],
        outcome=outcome,
        lease_id=completed_lease_id,
        correlation_id=expected_correlation,
        dispatch_id=completed_dispatch_id,
    )


def poll_results(config: dict[str, Any]) -> int:
    count = 0
    for task in config.get("tasks", []):
        if task.get("status") not in RESULT_WAITING or not task.get("dispatch_id"):
            continue
        lease_id = task.get("lease_id")
        if not lease_id:
            continue
        if task.get("dispatch_id") != dispatch_id_for(task):
            # Old artifact identity belongs to an earlier lease and must not be polled as current.
            continue
        result = find_result(lease_id)
        if result is None:
            continue
        ingest_result(config, task, result)
        count += 1
    return count


def _load_runtime(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save(path: Path, summary_path: Path, config: dict[str, Any]) -> None:
    am.atomic_json(path, config)
    am.atomic_json(summary_path, am.summarize(config))


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS agent dispatch/result transport")
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    parser.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", "main"))
    parser.add_argument("--mode", choices=("poll", "dispatch", "both"), default="both")
    args = parser.parse_args()
    path = Path(args.runtime)
    summary_path = Path(args.summary)
    config = _load_runtime(path)
    if config is None:
        print(json.dumps({"dispatched": 0, "ingested": 0, "reason": "runtime_missing"}, sort_keys=True))
        return 0
    am.validate_config(config)
    am.enforce_owner_boundaries(config)
    ingested = poll_results(config) if args.mode in {"poll", "both"} else 0
    dispatched = dispatch_pending(config, ref=args.ref) if args.mode in {"dispatch", "both"} else 0
    _save(path, summary_path, config)
    print(json.dumps({"dispatched": dispatched, "ingested": ingested, "summary": am.summarize(config)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
