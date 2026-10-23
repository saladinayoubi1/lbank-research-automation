"""Exact-endpoint regression for terminal Strategy Finder stages and recovery intake."""
from __future__ import annotations

from copy import deepcopy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import nexus_strategy_discovery_controller as controller
import nexus_strategy_discovery_recovery as recovery
import nexus_strategy_discovery_feedback as feedback
import nexus_strategy_discovery_rotation as rotation


def terminal_input():
    baseline = controller.build_status(ROOT)
    frontiers = [row for row in baseline["search_stages"] if row["rotation_eligible"]]
    assert len(frontiers) == 2
    fb = feedback.empty_state()
    core = {key: value for key, value in fb.items() if key != "state_digest"}
    core["outcomes"] = [
        {
            "experiment_sha256": row["frontier_sha256"],
            "outcome": "completed_no_qualification",
            "workflow_conclusion": "success",
        }
        for row in frontiers
    ]
    fb = {**core, "state_digest": feedback._digest(core)}
    state = rotation.empty_state()
    status = controller.build_status(ROOT, feedback_state=fb)
    blocked_core = {
        "schema_version": "nexus.strategy-discovery-blocked.v1",
        "status": "NEEDS_NEW_REVIEWED_MECHANISM",
        "reason": "all_exact_reviewed_frontiers_terminal",
        "previous_rotation_state_digest": state["state_digest"],
        "previous_feedback_state_digest": fb["state_digest"],
        "dispatch_allowed": False,
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    blocked = {**blocked_core, "blocked_digest": rotation._digest(blocked_core)}
    catalog = json.loads(
        (ROOT / "research" / "reviewed_composite_mechanisms_v1.json").read_text(encoding="utf-8")
    )
    return status, blocked, state, fb, catalog


def test_controller_separates_static_code_ready_from_verified_terminal_feedback():
    without = controller.build_status(ROOT)
    assert without["summary"]["ready_frontier_stage_count"] == 2
    assert without["summary"]["feedback_verified_for_frontier"] is False
    with_feedback, _, _, _, _ = terminal_input()
    assert with_feedback["controller_verified"] is True
    assert with_feedback["summary"]["ready_frontier_stage_count"] == 0
    assert with_feedback["summary"]["terminal_frontier_stage_count"] == 2
    assert with_feedback["summary"]["ready_legacy_validation_stage_count"] == 6
    assert with_feedback["next_research_action"] == "design_and_independently_review_new_mechanism"
    assert all(
        row["status"] == "FRONTIER_TERMINAL_REQUIRES_NEW_MECHANISM"
        for row in with_feedback["search_stages"] if row["rotation_eligible"]
    )


def test_rejected_failed_workflow_and_changed_exact_fingerprint_stays_ready():
    status, _, _, fb, _ = terminal_input()
    previous = {k: v for k, v in fb.items() if k != "state_digest"}
    previous["outcomes"][0]["workflow_conclusion"] = "failure"
    revised = {**previous, "state_digest": feedback._digest(previous)}
    dynamic = controller.build_status(ROOT, feedback_state=revised)
    assert dynamic["summary"]["ready_frontier_stage_count"] == 1
    assert dynamic["summary"]["terminal_frontier_stage_count"] == 1
    assert dynamic["next_research_action"] == "nexus_multitimeframe_strategy_discovery"


def test_recovery_is_evidence_bound_and_never_creates_strategy_candidate():
    status, blocked, state, fb, catalog = terminal_input()
    result = recovery.build_recovery(status, blocked, state, fb, catalog)
    assert result["status"] == "RESEARCH_DESIGN_REVIEW_REQUIRED"
    assert result["terminal_frontier_count"] == 2
    assert result["reviewed_design_count"] == len(catalog["mechanisms"]) >= 20
    assert result["unverified_historical_novelty_count"] == result["reviewed_design_count"]
    assert result["request_automatic_search_dispatch"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False
    assert result["new_strategy_proven_profitable"] is False
    assert result["recovery_digest"] == recovery.digest({
        k: v for k, v in result.items() if k != "recovery_digest"
    })
    assert all(
        row["dispatch_allowed"] is False
        and row["implementation_tested"] is False
        and row["historical_novelty_verified"] is False
        for row in result["design_review_queue"]
    )
    assert result["source_input_gap_design_count"] > 0


@pytest.mark.parametrize("tamper", ["blocked", "controller", "rotation", "feedback", "catalog"])
def test_tampering_any_source_hard_fails(tamper):
    status, blocked, state, fb, catalog = terminal_input()
    a, b, c, d, e = map(deepcopy, (status, blocked, state, fb, catalog))
    if tamper == "blocked":
        b["dispatch_allowed"] = True
    elif tamper == "controller":
        a["summary"]["terminal_frontier_stage_count"] += 1
    elif tamper == "rotation":
        c["state_digest"] = "f" * 64
    elif tamper == "feedback":
        d["state_digest"] = "f" * 64
    else:
        e["mechanisms"][0]["id"] = "changed_with_no_review"
        e["mechanisms"][1]["id"] = "changed_with_no_review"
    with pytest.raises(recovery.StrategyDiscoveryRecoveryError):
        recovery.build_recovery(a, b, c, d, e)


def test_unverified_feedback_never_changes_frontier_status():
    _, _, _, fb, _ = terminal_input()
    fb["outcomes"][0]["experiment_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="unverified"):
        controller.build_status(ROOT, feedback_state=fb)


def test_workflow_wires_verified_recovery_and_disallows_auto_dispatch():
    text = (ROOT / ".github/workflows/nexus_strategy_discovery_rotation.yml").read_text(encoding="utf-8")
    assert "--feedback-state build/discovery/feedback-state.json --output build/discovery/controller-status.json" in text
    recovery_step = text.split("Produce exact-source design-review queue when frontier is exhausted", 1)[1].split(
        "Dispatch reviewed Research workflow", 1
    )[0]
    assert "steps.frontier-selection.outputs.recovery_allowed == 'true'" in recovery_step
    assert "steps.frontier-selection.outputs.ready == 'false'" not in recovery_step
    assert "nexus_strategy_discovery_recovery.py" in recovery_step
    assert "--reviewed-catalog research/reviewed_composite_mechanisms_v1.json" in recovery_step
    assert "nexus-strategy-discovery-recovery-plan" in text
    assert "name: nexus-strategy-discovery-rotation-state" in text
    dispatch_step = text.split("Dispatch reviewed Research workflow", 1)[1].split(
        "Commit rotation cursor only after accepted dispatch", 1
    )[0]
    assert "steps.frontier-selection.outputs.ready == 'true'" in dispatch_step


def test_cli_exhaustion_yields_review_plan_without_mutating_cursor(tmp_path):
    status, blocked, state, fb, catalog = terminal_input()
    inputs = {
        "controller": status, "blocked": blocked, "rotation-state": state,
        "feedback-state": fb, "reviewed-catalog": catalog,
    }
    for label, value in inputs.items():
        (tmp_path / (label + ".json")).write_text(json.dumps(value), encoding="utf-8")
    output = tmp_path / "recovery.json"
    before = (tmp_path / "rotation-state.json").read_bytes()
    argv = [sys.executable, str(ROOT / "scripts/nexus_strategy_discovery_recovery.py")]
    for label in inputs:
        argv += ["--" + label, str(tmp_path / (label + ".json"))]
    argv += ["--output", str(output)]
    child = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=45)
    assert child.returncode == 0, child.stderr
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "RESEARCH_DESIGN_REVIEW_REQUIRED"
    assert not result["request_automatic_search_dispatch"]
    assert (tmp_path / "rotation-state.json").read_bytes() == before
