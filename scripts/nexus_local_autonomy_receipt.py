"""Bounded owner-local proof for the Windows autonomous queue.

Only status counts, an immutable digest and exact GitHub execution identity may
reach the job log. The private queue, heartbeat paths and runtime state are
NEVER uploaded or copied into GitHub artifact staging.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT = "nexus.owner-local-autonomy-receipt.v1"
SHA = re.compile(r"^[0-9a-f]{40}$")
RUN = re.compile(r"^[1-9][0-9]{0,19}$")
STATES = ("pending", "running", "completed", "failed", "blocked", "superseded")
MAX_PRIVATE_BYTES = 2_000_000


class PrivateReceiptError(ValueError):
    pass


def _read_private(path: Path) -> tuple[Any, str]:
    try:
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 2 <= before.st_size <= MAX_PRIVATE_BYTES):
            raise PrivateReceiptError("local autonomy state entry unsafe")
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            raw = stream.read(MAX_PRIVATE_BYTES + 1)
            after = os.fstat(stream.fileno())
        if (len(raw) != before.st_size or len(raw) > MAX_PRIVATE_BYTES
                or (before.st_dev, before.st_ino, before.st_size)
                != (after.st_dev, after.st_ino, after.st_size)):
            raise PrivateReceiptError("local autonomy state changed during read")
        value = json.loads(raw.decode("utf-8"))
        return value, hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PrivateReceiptError("local autonomy evidence unreadable") from exc


def build_receipt(
    state_root: Path, runner_workspace: Path, source_sha: str, run_id: str,
    *, runner_name: str, now: float | None = None,
) -> dict[str, Any]:
    if not isinstance(source_sha, str) or not SHA.fullmatch(source_sha):
        raise PrivateReceiptError("exact autonomy source SHA missing")
    if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
        raise PrivateReceiptError("exact autonomy run ID missing")
    if runner_name != "NEXUS-LOCAL-RUNNER":
        raise PrivateReceiptError("unexpected local runner identity")
    root = Path(state_root)
    workspace = Path(runner_workspace)
    expected = workspace / "nexus-phase3-state"
    if (not root.is_absolute() or not workspace.is_absolute()
            or root.is_symlink() or workspace.is_symlink()
            or root.resolve() != expected.resolve()
            or not root.is_dir()):
        raise PrivateReceiptError("owner-local autonomy root boundary mismatch")
    heartbeat, heartbeat_sha = _read_private(root / "worker-heartbeat.json")
    queue, queue_sha = _read_private(root / "autonomous-queue.json")
    if not isinstance(heartbeat, dict) or not isinstance(queue, list) or len(queue) > 10_000:
        raise PrivateReceiptError("invalid bounded local autonomy records")
    stamp = heartbeat.get("time")
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
        raise PrivateReceiptError("local autonomy heartbeat lacks a timestamp")
    age = (time.time() if now is None else now) - stamp
    if not 0 <= age <= 600 or heartbeat.get("state") != "cycle_complete":
        raise PrivateReceiptError("local autonomy heartbeat incomplete or stale")
    if (heartbeat.get("exit_reason") not in {"lease_expired", "task_quota", "idle"}
            or type(heartbeat.get("tasks_run")) is not int
            or heartbeat["tasks_run"] < 0):
        raise PrivateReceiptError("local autonomy completion reason invalid")
    counts = {k: 0 for k in STATES}
    for task in queue:
        if not isinstance(task, dict):
            raise PrivateReceiptError("local autonomy queue row invalid")
        status = task.get("status", "pending")
        if status not in counts:
            raise PrivateReceiptError("local autonomy queue state invalid")
        counts[status] += 1
    report = {
        "contract_version": CONTRACT,
        "decision": "OWNER_LOCAL_CYCLE_VERIFIED_ONLY",
        "source_sha": source_sha,
        "workflow_run_id": run_id,
        "generated_at_utc": datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat(),
        "runner_name": runner_name,
        "runner_identity_checked": True,
        "owner_durable_state": True,
        "last_heartbeat_age_seconds": round(age, 1),
        "exit_reason": heartbeat["exit_reason"],
        "tasks_run": heartbeat["tasks_run"],
        "queue_status_counts": counts,
        "heartbeat_sha256": heartbeat_sha,
        "queue_sha256": queue_sha,
        "paper_only": True,
        "live_trading_authority": False,
        "no_private_state_export": True,
        "qualification_authority": False,
    }
    raw = json.dumps(report, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    report["receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    return report


def _store_local(root: Path, report: dict[str, Any]) -> None:
    """Only our own receipt file is replaced, never the runner's durable state."""
    temp_path: Path | None = None
    try:
        payload = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".nexus-autonomy-receipt-", suffix=".tmp",
            dir=root, delete=False,
        ) as stream:
            temp_path = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temp_path.replace(root / "autonomy-receipt.json")
    except OSError as exc:
        raise PrivateReceiptError("failed to persist owner-only receipt") from exc
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def main() -> None:
    root = Path(os.environ["NEXUS_STATE_DIR"])
    report = build_receipt(
        root, Path(os.environ["RUNNER_WORKSPACE"]),
        os.environ["GITHUB_SHA"], os.environ["GITHUB_RUN_ID"],
        runner_name=os.environ["RUNNER_NAME"],
    )
    _store_local(root, report)
    # Only an allowlisted, non-reversible operational synopsis enters GitHub logs.
    # Queue and heartbeat digests are retained ONLY in the owner-local receipt.
    safe = {key: report[key] for key in (
        "contract_version", "decision", "source_sha", "workflow_run_id",
        "generated_at_utc", "runner_name", "last_heartbeat_age_seconds",
        "exit_reason", "tasks_run", "queue_status_counts", "paper_only",
        "live_trading_authority", "no_private_state_export",
        "qualification_authority", "receipt_sha256",
    )}
    print(json.dumps(safe, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
