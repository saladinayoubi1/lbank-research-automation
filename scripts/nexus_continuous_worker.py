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

PRIORITY_ORDER = [
    "product_research",
    "phase_blocker",
    "stability",
    "automation",
    "development_speed",
    "security",
    "maintainability",
    "user_experience",
    "monetization",
    "backlog",
]
LANE_ORDER = {"product": 0, "blocker": 1, "general": 2, "backlog": 9}


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


def _deps_complete(mission: dict, by_id: dict[str, dict]) -> bool:
    return all(by_id.get(mid, {}).get("status") == "completed" for mid in mission.get("dependencies", []))


def _rank(mission: dict) -> tuple[int, int, str]:
    lane = LANE_ORDER.get(mission.get("lane", "general"), LANE_ORDER["general"])
    try:
        priority = PRIORITY_ORDER.index(mission.get("priority"))
    except ValueError:
        priority = len(PRIORITY_ORDER)
    return lane, priority, str(mission.get("id", ""))


def select_ready() -> list[str]:
    queue = json.loads(QUEUE.read_text(encoding="utf-8"))
    missions = queue.get("missions", [])
    by_id = {str(m.get("id")): m for m in missions}
    ready = [
        m for m in missions
        if m.get("id") in COMMANDS
        and m.get("status") in {"active", "queued"}
        and _deps_complete(m, by_id)
    ]
    ready.sort(key=_rank)

    max_parallel = max(1, int(queue.get("selectionPolicy", {}).get("maxParallelMissions", 3)))
    selected: list[dict] = []
    selected_ids: set[str] = set()

    product_ready = [m for m in ready if m.get("lane", "general") == "product"]
    product_slots = (max_parallel + 1) // 2 if product_ready else 0
    for mission in product_ready[:product_slots]:
        selected.append(mission)
        selected_ids.add(str(mission["id"]))

    for mission in ready:
        if len(selected) >= max_parallel:
            break
        mid = str(mission["id"])
        if mid in selected_ids:
            continue
        selected.append(mission)
        selected_ids.add(mid)

    return [str(m["id"]) for m in selected]


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
                except Exception as exc:
                    results.append({"mission_id": mid, "verified": False, "error": repr(exc)})
    payload = {
        "version": 2,
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
                error = {"version": 2, "pid": os.getpid(), "timestamp": now_iso(), "fatal_cycle_error": repr(exc)}
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
