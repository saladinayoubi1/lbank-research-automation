"""Bounded autonomous orchestrator for NEXUS.

Turns repository-maintained tasks into deterministic, repository-controlled execution
plans. External AI providers are intentionally excluded from autonomous planning so
scheduled runs cannot consume credentials or incur provider billing.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

QUEUE = Path(".nexus/autonomous-queue.json")
STATE = Path("build/autonomy/state.json")
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


def validate_task(task: dict[str, Any]) -> tuple[bool, str]:
    name = str(task.get("task", "")).strip()
    detail = str(task.get("reason", "")).lower()
    if name not in ALLOWED_TASKS:
        return False, "task_not_allowlisted"
    if any(term in detail for term in PROTECTED_TERMS):
        return False, "protected_boundary"
    return True, "ok"


def choose_next(queue: list[dict[str, Any]]) -> dict[str, Any] | None:
    for task in queue:
        if task.get("status", "pending") != "pending":
            continue
        ok, reason = validate_task(task)
        if ok:
            return task
        task["status"] = "blocked"
        task["block_reason"] = reason
    return None


def main() -> None:
    queue = load_json(QUEUE, [])
    if not isinstance(queue, list):
        raise SystemExit("invalid autonomous queue")
    state = load_json(STATE, {"completed": [], "failed": [], "blocked": []})
    task = choose_next(queue)
    if task is None:
        state.pop("next_task", None)
        state.pop("next_reason", None)
        state.pop("next_source", None)
        save_json(QUEUE, queue)
        save_json(STATE, state)
        print(json.dumps({"ok": True, "action": "none", "reason": "no_safe_task"}, sort_keys=True))
        return
    # The workflow maps this validated symbolic task to a fixed command. No arbitrary shell is accepted.
    state["next_task"] = task["task"]
    state["next_reason"] = task.get("reason", "")
    state["next_source"] = "queue"
    save_json(QUEUE, queue)
    save_json(STATE, state)
    print("NEXUS_NEXT_TASK=" + task["task"])
    print(json.dumps({"ok": True, "task": task["task"], "source": "queue"}, sort_keys=True))


if __name__ == "__main__":
    main()
