"""Evidence-bound daily rotation over reviewed NEXUS strategy-search workflows."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping


STATE_SCHEMA = "nexus.strategy-discovery-rotation-state.v1"
PLAN_SCHEMA = "nexus.strategy-discovery-rotation-plan.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class StrategyDiscoveryRotationError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise StrategyDiscoveryRotationError("rotation evidence is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(dict(value), indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyDiscoveryRotationError("rotation input is unavailable") from exc
    if not isinstance(value, dict):
        raise StrategyDiscoveryRotationError("rotation input is not an object")
    return value


def empty_state() -> dict[str, Any]:
    core = {
        "schema_version": STATE_SCHEMA,
        "next_index": 0,
        "dispatch_count": 0,
        "last_dispatch": None,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def load_state(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return empty_state()
    value = load_json(target)
    core = dict(value)
    claimed = core.pop("state_digest", None)
    if (
        core.get("schema_version") != STATE_SCHEMA
        or not isinstance(core.get("next_index"), int) or isinstance(core.get("next_index"), bool)
        or core["next_index"] < 0
        or not isinstance(core.get("dispatch_count"), int) or core["dispatch_count"] < 0
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("live_trading_authority") is not False
        or core.get("qualification_authority") is not False
        or core.get("automatic_strategy_promotion") is not False
        or claimed != _digest(core)
    ):
        raise StrategyDiscoveryRotationError("rotation state verification failed")
    return value


def build_plan(controller: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    if (
        controller.get("schema") != "nexus.strategy-discovery-controller.v1"
        or controller.get("controller_verified") is not True
        or controller.get("paper_only") is not True
        or controller.get("live_trading_authority") is not False
        or controller.get("qualification_claimed") is not False
    ):
        raise StrategyDiscoveryRotationError("strategy discovery controller is not verified")
    stages = [
        row for row in controller.get("search_stages", [])
        if isinstance(row, Mapping) and row.get("status") == "READY_FOR_RESEARCH_DISPATCH"
    ]
    if not stages:
        raise StrategyDiscoveryRotationError("no reviewed strategy-search workflow is ready")
    index = int(state["next_index"]) % len(stages)
    selected = stages[index]
    workflow = str(selected.get("workflow", ""))
    if not workflow.startswith(".github/workflows/") or not workflow.endswith((".yml", ".yaml")):
        raise StrategyDiscoveryRotationError("selected workflow path is invalid")
    core = {
        "schema_version": PLAN_SCHEMA,
        "state_digest": state["state_digest"],
        "stage_count": len(stages),
        "selected_index": index,
        "stage": selected["stage"],
        "workflow": workflow,
        "experiment_id": selected.get("experiment_id"),
        "experiment_sha256": selected.get("experiment_sha256"),
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "plan_digest": _digest(core)}


def commit_dispatch(
    state: Mapping[str, Any], plan: Mapping[str, Any], *, source_sha: str, run_id: str,
) -> dict[str, Any]:
    source_sha = str(source_sha).strip().lower()
    if not _SHA_RE.fullmatch(source_sha) or not str(run_id).isdigit():
        raise StrategyDiscoveryRotationError("dispatch source binding is invalid")
    plan_core = dict(plan)
    claimed = plan_core.pop("plan_digest", None)
    if (
        claimed != _digest(plan_core)
        or plan_core.get("schema_version") != PLAN_SCHEMA
        or plan_core.get("state_digest") != state.get("state_digest")
        or plan_core.get("research_only") is not True
        or plan_core.get("paper_only") is not True
        or plan_core.get("live_trading_authority") is not False
        or plan_core.get("qualification_authority") is not False
        or plan_core.get("automatic_strategy_promotion") is not False
    ):
        raise StrategyDiscoveryRotationError("dispatch plan verification failed")
    core = {
        "schema_version": STATE_SCHEMA,
        "next_index": (int(plan["selected_index"]) + 1) % int(plan["stage_count"]),
        "dispatch_count": int(state["dispatch_count"]) + 1,
        "last_dispatch": {
            "stage": plan["stage"],
            "workflow": plan["workflow"],
            "experiment_id": plan.get("experiment_id"),
            "experiment_sha256": plan.get("experiment_sha256"),
            "source_sha": source_sha,
            "run_id": str(run_id),
            "plan_digest": plan["plan_digest"],
        },
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--controller-status", type=Path, required=True)
    plan.add_argument("--state", type=Path, required=True)
    plan.add_argument("--output", type=Path, required=True)
    commit = sub.add_parser("commit")
    commit.add_argument("--state", type=Path, required=True)
    commit.add_argument("--plan", type=Path, required=True)
    commit.add_argument("--source-sha", required=True)
    commit.add_argument("--run-id", required=True)
    commit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = load_state(args.state)
    if args.command == "plan":
        value = build_plan(load_json(args.controller_status), state)
    else:
        value = commit_dispatch(
            state, load_json(args.plan), source_sha=args.source_sha, run_id=args.run_id,
        )
    _atomic(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
