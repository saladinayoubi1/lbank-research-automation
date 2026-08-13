from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "config" / "nexus-mission-queue.json"
STATE_DIR = ROOT / ".nexus_runtime"
HEARTBEAT = STATE_DIR / "continuous-worker-heartbeat.json"
LOCK = STATE_DIR / "continuous-worker.lock"

COMMANDS = {
    "M-010": [sys.executable, str(ROOT / "scripts" / "nexus_phase3_task.py"), "evidence"],
    "M-011": [sys.executable, str(ROOT / "scripts" / "nexus_phase3_task.py"), "strategy"],
    "M-012": [sys.executable, str(ROOT / "scripts" / "nexus_phase3_task.py"), "gates"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def acquire_lock() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text(encoding="utf-8").strip())
            if pid > 0:
                os.kill(pid, 0)
                raise RuntimeError(f"continuous worker already running pid={pid}")
        except ProcessLookupError:
            pass
        except (ValueError, PermissionError):
            raise RuntimeError("ambiguous worker lock; fail closed")
    LOCK.write_text(str(os.getpid()), encoding="utf-8")


def release_lock() -> None:
    try:
        if LOCK.exists() and LOCK.read_text(encoding="utf-8").strip() == str(os.getpid()):
            LOCK.unlink()
    except OSError:
        pass


def select_ready() -> list[str]:
    proc = subprocess.run(
        ["node", str(ROOT / "scripts" / "nexus_orchestrator.js"), str(QUEUE)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"orchestrator failed: {proc.stderr.strip()}")
    state = json.loads(proc.stdout)
    return [mid for mid in state.get("readyMissionIds", []) if mid in COMMANDS]


def run_mission(mission_id: str) -> dict:
    started = now_iso()
    cmd = COMMANDS[mission_id]
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=900)
    return {
        "mission_id": mission_id,
        "started_at": started,
        "finished_at": now_iso(),
        "returncode": proc.returncode,
        "stdout": proc.stdout[-8000:],
        "stderr": proc.stderr[-8000:],
        "verified": proc.returncode == 0,
    }


def cycle() -> dict:
    ready = select_ready()
    results = []
    if ready:
        with ThreadPoolExecutor(max_workers=min(3, len(ready))) as pool:
            futures = {pool.submit(run_mission, mid): mid for mid in ready}
            for future in as_completed(futures):
                mid = futures[future]
                try:
                    results.append(future.result())
                except Exception as exc:  # fail one mission without idling independent lanes
                    results.append({"mission_id": mid, "verified": False, "error": repr(exc)})
    payload = {
        "version": 1,
        "pid": os.getpid(),
        "timestamp": now_iso(),
        "ready_missions": ready,
        "results": sorted(results, key=lambda item: item.get("mission_id", "")),
    }
    write_json_atomic(HEARTBEAT, payload)
    return payload


def main() -> int:
    once = "--once" in sys.argv
    interval = int(os.environ.get("NEXUS_WORKER_INTERVAL_SECONDS", "15"))
    max_runtime = int(os.environ.get("NEXUS_WORKER_MAX_RUNTIME_SECONDS", "0"))
    started = time.monotonic()
    acquire_lock()
    try:
        while True:
            try:
                payload = cycle()
                print(json.dumps(payload, sort_keys=True), flush=True)
            except Exception as exc:
                error = {"version": 1, "pid": os.getpid(), "timestamp": now_iso(), "fatal_cycle_error": repr(exc)}
                write_json_atomic(HEARTBEAT, error)
                print(json.dumps(error, sort_keys=True), file=sys.stderr, flush=True)
            if once:
                break
            if max_runtime and time.monotonic() - started >= max_runtime:
                break
            time.sleep(max(5, interval))
    finally:
        release_lock()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
