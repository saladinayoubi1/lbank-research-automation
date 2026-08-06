"""Single-worker persistent task queue for low-memory local coordination."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
QUEUE_ROOT = ROOT / "data" / "task_queue"
PENDING = QUEUE_ROOT / "pending"
RUNNING = QUEUE_ROOT / "running"
DONE = QUEUE_ROOT / "done"
FAILED = QUEUE_ROOT / "failed"
LOCK = QUEUE_ROOT / "worker.lock"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    for path in (PENDING, RUNNING, DONE, FAILED):
        path.mkdir(parents=True, exist_ok=True)


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def enqueue(name: str, command: list[str], cwd: str | None = None) -> Path:
    ensure_dirs()
    task_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": task_id,
        "name": name,
        "command": command,
        "cwd": cwd or str(ROOT),
        "status": "pending",
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "returncode": None,
        "stdout": "",
        "stderr": "",
    }
    path = PENDING / f"{task_id}.json"
    atomic_write(path, payload)
    return path


def acquire_lock() -> int:
    ensure_dirs()
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError("A queue worker is already running.") from exc
    os.write(fd, str(os.getpid()).encode())
    return fd


def release_lock(fd: int) -> None:
    try:
        os.close(fd)
    finally:
        LOCK.unlink(missing_ok=True)


def next_task() -> Path | None:
    ensure_dirs()
    tasks = sorted(PENDING.glob("*.json"))
    return tasks[0] if tasks else None


def run_one(task_path: Path) -> dict[str, Any]:
    payload = json.loads(task_path.read_text(encoding="utf-8"))
    running_path = RUNNING / task_path.name
    task_path.replace(running_path)
    payload["status"] = "running"
    payload["started_at"] = now_iso()
    atomic_write(running_path, payload)

    result = subprocess.run(
        [str(part) for part in payload["command"]],
        cwd=payload.get("cwd") or ROOT,
        capture_output=True,
        text=True,
        shell=False,
    )
    payload["returncode"] = result.returncode
    payload["stdout"] = result.stdout[-20000:]
    payload["stderr"] = result.stderr[-20000:]
    payload["finished_at"] = now_iso()
    payload["status"] = "done" if result.returncode == 0 else "failed"
    target = (DONE if result.returncode == 0 else FAILED) / running_path.name
    atomic_write(running_path, payload)
    running_path.replace(target)
    return payload


def worker(once: bool, poll_seconds: float) -> int:
    fd = acquire_lock()
    try:
        while True:
            task_path = next_task()
            if task_path is None:
                if once:
                    return 0
                time.sleep(max(1.0, poll_seconds))
                continue
            payload = run_one(task_path)
            print(json.dumps({"id": payload["id"], "status": payload["status"], "returncode": payload["returncode"]}))
            if once:
                return int(payload["returncode"] or 0)
    finally:
        release_lock(fd)


def status() -> dict[str, int]:
    ensure_dirs()
    return {
        "pending": len(list(PENDING.glob("*.json"))),
        "running": len(list(RUNNING.glob("*.json"))),
        "done": len(list(DONE.glob("*.json"))),
        "failed": len(list(FAILED.glob("*.json"))),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="Add one task to the queue")
    add.add_argument("--name", required=True)
    add.add_argument("command", nargs=argparse.REMAINDER)

    work = sub.add_parser("worker", help="Run tasks one at a time")
    work.add_argument("--once", action="store_true")
    work.add_argument("--poll-seconds", type=float, default=3.0)

    sub.add_parser("status", help="Show queue counts")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.action == "add":
        if not args.command:
            raise SystemExit("No command supplied.")
        path = enqueue(args.name, args.command)
        print(path)
        return 0
    if args.action == "worker":
        return worker(args.once, args.poll_seconds)
    print(json.dumps(status(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
