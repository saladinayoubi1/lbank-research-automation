"""Fail-closed Strategy Finder exhaustion recovery / research design intake.

This does not remove the stop on exhausted experiments. It turns a verified
terminal rotation into a deterministic, data-scoped implementation review queue.
Catalog entries are DESIGN contracts, not executed signals or new candidates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nexus_strategy_discovery_feedback import load_state as load_feedback
from nexus_strategy_discovery_rotation import load_state as load_rotation
from nexus_strategy_research_feedback import (
    ResearchFeedbackError, _PROVEN_INPUTS, validate_catalog,
)

SCHEMA = "nexus.strategy-discovery-recovery-review.v1"


class StrategyDiscoveryRecoveryError(ValueError):
    pass


def digest(value: Mapping[str, Any]) -> str:
    try:
        payload = json.dumps(dict(value), sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise StrategyDiscoveryRecoveryError("non-canonical research recovery evidence") from exc
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise StrategyDiscoveryRecoveryError("missing, linked, or oversized recovery input")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, OSError, ValueError) as exc:
        raise StrategyDiscoveryRecoveryError("recovery evidence is unreadable") from exc
    if not isinstance(data, dict):
        raise StrategyDiscoveryRecoveryError("recovery evidence must be an object")
    return data


def build_recovery(
    controller: Mapping[str, Any], blocked: Mapping[str, Any],
    rotation: Mapping[str, Any], feedback: Mapping[str, Any],
    reviewed_catalog: Mapping[str, Any],
) -> dict[str, Any]:
    controller_core = {key: value for key, value in controller.items() if key != "status_sha256"}
    blocked_core = {key: value for key, value in blocked.items() if key != "blocked_digest"}
    if (
        controller.get("schema") != "nexus.strategy-discovery-controller.v1"
        or controller.get("status_sha256") != digest(controller_core)
        or controller.get("controller_verified") is not True
        or controller.get("paper_only") is not True
        or controller.get("live_trading_authority") is not False
        or controller.get("qualification_claimed") is not False
        or controller.get("summary", {}).get("feedback_verified_for_frontier") is not True
        or blocked.get("schema_version") != "nexus.strategy-discovery-blocked.v1"
        or blocked.get("blocked_digest") != digest(blocked_core)
        or blocked.get("status") != "NEEDS_NEW_REVIEWED_MECHANISM"
        or blocked.get("reason") != "all_exact_reviewed_frontiers_terminal"
        or blocked.get("dispatch_allowed") is not False
        or blocked.get("research_only") is not True
        or blocked.get("paper_only") is not True
        or blocked.get("qualification_authority") is not False
        or blocked.get("automatic_strategy_promotion") is not False
        or blocked.get("live_trading_authority") is not False
        or blocked.get("previous_rotation_state_digest") != rotation.get("state_digest")
        or blocked.get("previous_feedback_state_digest") != feedback.get("state_digest")
    ):
        raise StrategyDiscoveryRecoveryError("unverified blocked frontier cannot create research work")
    stages = controller.get("search_stages")
    if not isinstance(stages, list):
        raise StrategyDiscoveryRecoveryError("controller search stages unavailable")
    frontier = [row for row in stages if row.get("rotation_eligible") is True]
    terminal = [
        row for row in frontier
        if row.get("status") == "FRONTIER_TERMINAL_REQUIRES_NEW_MECHANISM"
        and row.get("terminal_evidence") == "exact_successful_feedback_fingerprint"
    ]
    if not terminal or any(row.get("status") == "READY_FOR_RESEARCH_DISPATCH" for row in frontier):
        raise StrategyDiscoveryRecoveryError("no exact exhaust-only recovery state established")
    try:
        mechanisms = validate_catalog(reviewed_catalog)
    except ResearchFeedbackError as exc:
        raise StrategyDiscoveryRecoveryError("reviewed mechanism catalog failed validation") from exc
    queue = []
    for mechanism in mechanisms:
        required = set(mechanism["inputs"])
        missing = sorted(required - _PROVEN_INPUTS)
        queue.append({
            "mechanism_id": mechanism["id"],
            "structural_fingerprint": mechanism["mechanism_sha256"],
            "source_inputs": sorted(required),
            "unverified_source_inputs": missing,
            "input_contract": (
                "OHLCV_INPUTS_DESCRIBED_NOT_RUNTIME_PROVEN"
                if not missing else "MISSING_INDEPENDENT_SOURCE_PROOF"
            ),
            "historical_novelty_verified": False,
            "implementation_tested": False,
            "dispatch_allowed": False,
            "qualification_authority": False,
            "next_gate": (
                "independently_verify_input_evidence_and_novelty_ledger"
                if not missing else "verify_missing_data_provenance_then_novelty"
            ),
        })
    queue.sort(key=lambda row: (bool(row["unverified_source_inputs"]), row["mechanism_id"]))
    core = {
        "schema_version": SCHEMA,
        "status": "RESEARCH_DESIGN_REVIEW_REQUIRED",
        "root_cause": "no_unexhausted_exact_reviewed_frontier_dispatch",
        "blocked_digest": blocked["blocked_digest"],
        "controller_status_sha256": controller["status_sha256"],
        "rotation_state_digest": rotation["state_digest"],
        "feedback_state_digest": feedback["state_digest"],
        "reviewed_catalog_digest": digest(reviewed_catalog),
        "terminal_frontier_count": len(terminal),
        "terminal_frontier_stages": sorted(row["stage"] for row in terminal),
        "reviewed_design_count": len(queue),
        "source_input_gap_design_count": sum(bool(row["unverified_source_inputs"]) for row in queue),
        "unverified_historical_novelty_count": len(queue),
        "design_review_queue": queue,
        "next_action": (
            "verify_exact_evaluated_mechanism_ledger_and_build_one_genuinely_new_"
            "source_bound_cost_aware_hypothesis_with_independent_backtests"
        ),
        "request_automatic_search_dispatch": False,
        "new_hypothesis_automatically_implemented": False,
        "new_strategy_proven_profitable": False,
        "research_only": True,
        "paper_only": True,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "qualification_authority": False,
    }
    return {**core, "recovery_digest": digest(core)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", type=Path, required=True)
    parser.add_argument("--blocked", type=Path, required=True)
    parser.add_argument("--rotation-state", type=Path, required=True)
    parser.add_argument("--feedback-state", type=Path, required=True)
    parser.add_argument("--reviewed-catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.rotation_state.is_symlink() or not args.rotation_state.is_file():
        raise StrategyDiscoveryRecoveryError("verified rotation state is missing")
    rotation = load_rotation(args.rotation_state)
    feedback = load_feedback(args.feedback_state, require_existing=True)
    value = build_recovery(
        _read(args.controller), _read(args.blocked), rotation, feedback,
        _read(args.reviewed_catalog),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(args.output.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, args.output)
    print(json.dumps({
        "status": value["status"],
        "terminal_frontier_count": value["terminal_frontier_count"],
        "reviewed_design_count": value["reviewed_design_count"],
        "unverified_historical_novelty_count": value["unverified_historical_novelty_count"],
        "recovery_digest": value["recovery_digest"],
        "automatic_strategy_promotion": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
