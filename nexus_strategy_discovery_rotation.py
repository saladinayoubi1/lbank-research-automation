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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def build_plan(controller: Mapping[str, Any], state: Mapping[str, Any], feedback: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if (
        controller.get("schema") != "nexus.strategy-discovery-controller.v1"
        or controller.get("controller_verified") is not True
        or controller.get("paper_only") is not True
        or controller.get("live_trading_authority") is not False
        or controller.get("qualification_claimed") is not False
    ):
        raise StrategyDiscoveryRotationError("strategy discovery controller is not verified")
    exhausted: set[str] = set()
    resolved_completed: set[str] = set()
    if feedback is not None:
        if (
            feedback.get("schema_version") != "nexus.strategy-discovery-feedback.v1"
            or feedback.get("research_only") is not True
            or feedback.get("paper_only") is not True
            or feedback.get("qualification_authority") is not False
            or feedback.get("automatic_strategy_promotion") is not False
            or feedback.get("live_trading_authority") is not False
            or not isinstance(feedback.get("exhausted_experiment_sha256"), list)
            or not isinstance(feedback.get("outcomes"), list)
            or feedback.get("state_digest") != _digest(
                {k: v for k, v in feedback.items() if k != "state_digest"}
            )
        ):
            raise StrategyDiscoveryRotationError("strategy discovery feedback is not verified")
        exhausted = {str(item) for item in feedback["exhausted_experiment_sha256"]}
        # A successful, artifact-confirmed terminal result retires only the exact
        # experiment fingerprint. Positive candidate evidence advances to
        # review/requalification instead of being replayed as fresh discovery.
        # Failed, evidence-unavailable and requires-data outcomes remain retryable.
        terminal_outcomes = {
            "no_candidate",
            "exhausted",
            "candidate_evidence",
            "completed_no_qualification",
        }
        resolved_completed = {
            str(row["experiment_sha256"])
            for row in feedback["outcomes"]
            if isinstance(row, Mapping)
            and row.get("outcome") in terminal_outcomes
            and row.get("workflow_conclusion") == "success"
            and isinstance(row.get("experiment_sha256"), str)
            and _SHA256_RE.fullmatch(row["experiment_sha256"])
        }
    stages = [
        row for row in controller.get("search_stages", [])
        if (
            isinstance(row, Mapping)
            and row.get("status") == "READY_FOR_RESEARCH_DISPATCH"
            and row.get("rotation_eligible") is True
            and str(row.get("experiment_sha256")) not in exhausted
            and str(row.get("experiment_sha256")) not in resolved_completed
        )
    ]
    if not stages:
        if exhausted or resolved_completed:
            raise StrategyDiscoveryRotationError(
                "no untested reviewed Strategy Finder frontier remains; enqueue a genuinely new "
                "mechanism or changed source-bound frontier manifest rather than replaying legacy validation"
            )
        raise StrategyDiscoveryRotationError(
            "no reviewed Strategy Finder frontier workflow is ready; legacy validation is never an autonomous fallback"
        )
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
    plan.add_argument("--feedback-state", type=Path)
    commit = sub.add_parser("commit")
    commit.add_argument("--state", type=Path, required=True)
    commit.add_argument("--plan", type=Path, required=True)
    commit.add_argument("--source-sha", required=True)
    commit.add_argument("--run-id", required=True)
    commit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = load_state(args.state)
    if args.command == "plan":
        feedback = None
        if args.feedback_state and args.feedback_state.exists():
            feedback = load_json(args.feedback_state)
        value = build_plan(load_json(args.controller_status), state, feedback)
    else:
        value = commit_dispatch(
            state, load_json(args.plan), source_sha=args.source_sha, run_id=args.run_id,
        )
    _atomic(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())