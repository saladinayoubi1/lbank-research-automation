"""Outcome feedback for the existing NEXUS autonomous strategy-discovery rotation.

This module does not qualify or promote strategies. It records source-bound completed
research outcomes so the rotation can stop repeating an exhausted experiment
neighborhood and advance to a materially different reviewed search stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "nexus.strategy-discovery-feedback.v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class StrategyDiscoveryFeedbackError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError) as exc:
        raise StrategyDiscoveryFeedbackError("feedback evidence is not canonical JSON") from exc


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(dict(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def empty_state() -> dict[str, Any]:
    core = {
        "schema_version": SCHEMA,
        "processed_run_ids": [],
        "exhausted_experiment_sha256": [],
        "outcomes": [],
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "state_digest": _digest(core)}


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_state()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StrategyDiscoveryFeedbackError("feedback state unavailable") from exc
    if not isinstance(value, dict):
        raise StrategyDiscoveryFeedbackError("feedback state is not an object")
    core = dict(value)
    claimed = core.pop("state_digest", None)
    if (
        core.get("schema_version") != SCHEMA
        or core.get("research_only") is not True
        or core.get("paper_only") is not True
        or core.get("qualification_authority") is not False
        or core.get("automatic_strategy_promotion") is not False
        or core.get("live_trading_authority") is not False
        or not isinstance(core.get("processed_run_ids"), list)
        or not isinstance(core.get("exhausted_experiment_sha256"), list)
        or not isinstance(core.get("outcomes"), list)
        or claimed != _digest(core)
    ):
        raise StrategyDiscoveryFeedbackError("feedback state verification failed")
    return value


def _walk_json(value: Any):
    if isinstance(value, Mapping):
        yield value
        for item in value.values():
            yield from _walk_json(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json(item)


def _artifact_observations(root: Path) -> dict[str, bool]:
    flags = {
        "exhausted": False,
        "continue_research_no_promotion": False,
        "candidate_evidence": False,
        "requires_data": False,
    }
    if not root.exists():
        return flags
    for path in sorted(root.rglob("*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for row in _walk_json(value):
            if row.get("exhausted") is True:
                flags["exhausted"] = True
            decision = str(row.get("decision", "")).lower()
            status = str(row.get("status", "")).lower()
            reason = str(row.get("reason", "")).lower()
            if decision == "continue_research_no_promotion":
                flags["continue_research_no_promotion"] = True
            if status in {"paper_candidate", "candidate_evidence", "independent_test_passed"}:
                flags["candidate_evidence"] = True
            if status in {"requires_data", "data_unavailable"} or "requires_data" in reason:
                flags["requires_data"] = True
    return flags


def record_outcome(
    state: Mapping[str, Any],
    *,
    run: Mapping[str, Any],
    artifact_root: Path,
    stage: str,
    experiment_sha256: str,
    expected_source_sha: str | None = None,
) -> dict[str, Any]:
    run_id = str(run.get("databaseId", ""))
    if not run_id.isdigit():
        raise StrategyDiscoveryFeedbackError("research run id is invalid")
    if run.get("status") != "completed":
        raise StrategyDiscoveryFeedbackError("research run is not complete")
    if expected_source_sha is not None:
        if not re.fullmatch(r"[0-9a-f]{40}", expected_source_sha) or run.get("headSha") != expected_source_sha:
            raise StrategyDiscoveryFeedbackError("research outcome source SHA does not match dispatched receipt")
    if not _SHA256_RE.fullmatch(str(experiment_sha256).lower()):
        raise StrategyDiscoveryFeedbackError("experiment sha256 is invalid")
    if run_id in {str(x) for x in state.get("processed_run_ids", [])}:
        return dict(state)

    conclusion = str(run.get("conclusion", ""))
    if conclusion == "success" and not any(artifact_root.rglob("*.json")):
        raise StrategyDiscoveryFeedbackError("completed Research workflow has no readable outcome artifacts")
    flags = _artifact_observations(artifact_root)
    if conclusion != "success":
        outcome = "workflow_failed"
    elif flags["requires_data"]:
        outcome = "requires_data"
    elif flags["exhausted"]:
        outcome = "exhausted"
    elif flags["candidate_evidence"]:
        outcome = "candidate_evidence"
    elif flags["continue_research_no_promotion"]:
        outcome = "no_candidate"
    else:
        outcome = "completed_no_qualification"

    exhausted = list(state.get("exhausted_experiment_sha256", []))
    if outcome == "exhausted" and experiment_sha256 not in exhausted:
        exhausted.append(experiment_sha256)
    rows = list(state.get("outcomes", []))
    rows.append({
        "run_id": run_id,
        "stage": str(stage),
        "experiment_sha256": experiment_sha256,
        "outcome": outcome,
        "workflow_conclusion": conclusion,
        "artifact_flags": flags,
    })
    rows = rows[-256:]
    processed = [*state.get("processed_run_ids", []), run_id][-512:]
    core = {
        "schema_version": SCHEMA,
        "processed_run_ids": processed,
        "exhausted_experiment_sha256": sorted(set(exhausted)),
        "outcomes": rows,
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "state_digest": _digest(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--run-json", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--stage", required=True)
    parser.add_argument("--experiment-sha256", required=True)
    parser.add_argument("--expected-source-sha")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    state = load_state(args.state)
    run = json.loads(args.run_json.read_text(encoding="utf-8"))
    value = record_outcome(
        state,
        run=run,
        artifact_root=args.artifact_root,
        stage=args.stage,
        experiment_sha256=args.experiment_sha256,
        expected_source_sha=args.expected_source_sha,
    )
    _atomic(args.output, value)
    print(json.dumps(value, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())