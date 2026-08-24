"""Bounded autonomous orchestrator for NEXUS.

Turns repository-maintained tasks into deterministic, repository-controlled execution
plans. Mutable queue/state live in NEXUS_STATE_DIR when configured; tracked repository
files are only source/seed evidence and are never treated as durable runtime state.
External AI providers are intentionally excluded from autonomous planning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from nexus_execution_contract import (
    ExecutionContractError,
    validate_pre_execution_record,
    validate_task_record,
)

ROOT = Path(__file__).resolve().parent
SEED_QUEUE = ROOT / ".nexus" / "autonomous-queue.json"
STATE_DIR = Path(os.environ.get("NEXUS_STATE_DIR", str(ROOT / ".nexus"))).resolve()
QUEUE = STATE_DIR / "autonomous-queue.json"
STATE = STATE_DIR / "state.json"
ALLOWED_TASKS = {"health", "tests", "readiness", "zotero-status"}
PROTECTED_TERMS = {
    "production", "deploy", "live trading", "live-trading", "billing", "secret",
    "credential", "delete", "destructive", "permission", "withdraw", "transfer",
    "deepseek", "api key", "api-key", "external model", "external ai",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_queue() -> list[dict[str, Any]]:
    if QUEUE.exists():
        queue = load_json(QUEUE, [])
    elif SEED_QUEUE.exists():
        queue = load_json(SEED_QUEUE, [])
        save_json(QUEUE, queue)
    else:
        queue = []
    if not isinstance(queue, list):
        raise SystemExit("invalid autonomous queue")
    return queue


def validate_task(task: dict[str, Any]) -> tuple[bool, str]:
    name = str(task.get("task", "")).strip()
    detail = str(task.get("reason", "")).lower()
    if name not in ALLOWED_TASKS:
        return False, "task_not_allowlisted"
    if any(term in detail for term in PROTECTED_TERMS):
        return False, "protected_boundary"
    try:
        validate_task_record(task)
        validate_pre_execution_record(task.get("pre_execution"))
    except ExecutionContractError:
        return False, "execution_record_incomplete"
    return True, "ok"


def choose_next(queue: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in queue:
        if task.get("status", "pending") not in {"pending", "QUEUED"}:
            continue
        ok, reason = validate_task(task)
        if ok:
            return task
        # Preserve legacy queue vocabulary while all new contract-complete records
        # use the canonical execution-contract vocabulary.
        task["status"] = "BLOCKED" if task.get("task_id") else "blocked"
        task["block_reason"] = reason
    return None


def main() -> None:
    queue = load_queue()
    state = load_json(STATE, {"completed": [], "failed": [], "blocked": []})
    if not isinstance(state, dict):
        raise SystemExit("invalid autonomous state")
    task = choose_next(queue)
    if task is None:
        state.pop("next_task", None)
        state.pop("next_reason", None)
        state.pop("next_source", None)
        save_json(QUEUE, queue)
        save_json(STATE, state)
        print(json.dumps({"ok": True, "action": "none", "reason": "no_safe_task", "queue_path": str(QUEUE)}, sort_keys=True))
        return
    state["next_task"] = task["task"]
    state["next_reason"] = task.get("reason", "")
    state["next_source"] = "queue"
    save_json(QUEUE, queue)
    save_json(STATE, state)
    print("NEXUS_NEXT_TASK=" + task["task"])
    print(json.dumps({"ok": True, "task": task["task"], "source": "queue", "queue_path": str(QUEUE)}, sort_keys=True))


if __name__ == "__main__":
    main()
