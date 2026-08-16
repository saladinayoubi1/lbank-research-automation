from __future__ import annotations

import argparse
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import agent_manager as am

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")


def merge_definition(template: dict[str, Any], runtime: dict[str, Any] | None) -> dict[str, Any]:
    """Carry runtime task state forward while taking worker/policy definitions from git.

    New tasks from the repository are added. Removed tasks are retained as quarantined
    historical records instead of silently disappearing.
    """
    if not runtime or runtime.get("schema_version") != template.get("schema_version"):
        return deepcopy(template)

    merged = deepcopy(template)
    old_by_id = {t["id"]: t for t in runtime.get("tasks", []) if isinstance(t, dict) and t.get("id")}
    new_ids = {t["id"] for t in merged.get("tasks", [])}
    definition_keys = {
        "id", "title", "phase", "gate", "priority", "dependencies",
        "required_capabilities", "preferred_resources", "authority", "acceptance"
    }
    runtime_keys = {
        "status", "ready_at", "assigned_worker", "producer", "verifier", "lease_id",
        "leased_at", "heartbeat_at", "lease_expires_at", "attempt", "transient_retries",
        "triage_reason", "triage_started_at", "triage_mode", "required_output",
        "failure_class", "failure_evidence", "result_evidence", "verification_evidence",
        "verified_at", "blocked_reason"
    }
    for task in merged.get("tasks", []):
        old = old_by_id.get(task["id"])
        if not old:
            continue
        for key in runtime_keys:
            if key in old:
                task[key] = deepcopy(old[key])
        # Never let runtime state change immutable authority/dependency definitions.
        for key in definition_keys:
            if key in task:
                continue
            if key in old:
                task[key] = deepcopy(old[key])

    for old_id, old in old_by_id.items():
        if old_id in new_ids:
            continue
        historical = deepcopy(old)
        historical["status"] = "QUARANTINED"
        historical["blocked_reason"] = "task removed from current repository definition"
        merged["tasks"].append(historical)
    return merged


def load_runtime(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Durable wrapper for the NEXUS agent manager")
    parser.add_argument("--config", default=str(am.QUEUE_PATH))
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    args = parser.parse_args()

    template = am.load_config(Path(args.config))
    config = merge_definition(template, load_runtime(Path(args.runtime)))
    summary = am.cycle(config)
    am.atomic_json(Path(args.runtime), config)
    am.atomic_json(Path(args.summary), summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
