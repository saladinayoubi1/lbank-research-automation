from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_DIR = Path("data/agent_coordination")
SUPERVISOR_FILE = STATE_DIR / "supervisor.json"
LOG_DIR = STATE_DIR / "logs"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def start_process(name: str, cmd: list[str]) -> tuple[subprocess.Popen[str], Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = (LOG_DIR / f"{name}.log").open("a", encoding="utf-8")
    log.write(f"\n[{utcnow()}] START {' '.join(cmd)}\n")
    log.flush()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True)
    return proc, log


def main() -> int:
    parser = argparse.ArgumentParser(description="NEXUS local-node supervisor")
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--with-dashboard", action="store_true")
    args = parser.parse_args()

    poll = max(15, args.poll_seconds)
    children: dict[str, tuple[subprocess.Popen[str], Any, list[str]]] = {}

    orch_cmd = [sys.executable, "fast_agent_orchestrator.py", "--poll-seconds", str(poll)]
    proc, log = start_process("orchestrator", orch_cmd)
    children["orchestrator"] = (proc, log, orch_cmd)

    if args.with_dashboard and Path("start_local_dashboard.py").exists():
        dash_cmd = [sys.executable, "start_local_dashboard.py"]
        proc, log = start_process("dashboard", dash_cmd)
        children["dashboard"] = (proc, log, dash_cmd)

    try:
        while True:
            restarted: list[str] = []
            status: dict[str, Any] = {}
            for name, (proc, log, cmd) in list(children.items()):
                code = proc.poll()
                if code is not None:
                    log.write(f"[{utcnow()}] EXIT code={code}; restarting\n")
                    log.flush()
                    log.close()
                    new_proc, new_log = start_process(name, cmd)
                    children[name] = (new_proc, new_log, cmd)
                    proc, log = new_proc, new_log
                    restarted.append(name)
                    code = None
                status[name] = {"pid": proc.pid, "running": code is None}

            atomic_json(
                SUPERVISOR_FILE,
                {
                    "schema_version": 1,
                    "generated_at": utcnow(),
                    "supervisor_pid": os.getpid(),
                    "poll_seconds": poll,
                    "children": status,
                    "restarted_this_cycle": restarted,
                },
            )
            time.sleep(10)
    except KeyboardInterrupt:
        return 0
    finally:
        for proc, log, _ in children.values():
            if proc.poll() is None:
                proc.terminate()
            log.close()


if __name__ == "__main__":
    raise SystemExit(main())
