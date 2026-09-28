from __future__ import annotations

import json
from pathlib import Path

import pytest

from nexus_strategy_discovery_feedback import (
    StrategyDiscoveryFeedbackError,
    empty_state,
    record_outcome,
)
from nexus_strategy_discovery_rotation import build_plan, empty_state as empty_rotation_state


def _run(conclusion="success"):
    return {"databaseId": 123, "status": "completed", "conclusion": conclusion}


def _controller():
    return {
        "schema": "nexus.strategy-discovery-controller.v1",
        "controller_verified": True,
        "paper_only": True,
        "live_trading_authority": False,
        "qualification_claimed": False,
        "search_stages": [
            {
                "stage": "first",
                "workflow": ".github/workflows/first.yml",
                "experiment_id": "first",
                "experiment_sha256": "1" * 64,
                "status": "READY_FOR_RESEARCH_DISPATCH",
            },
            {
                "stage": "second",
                "workflow": ".github/workflows/second.yml",
                "experiment_id": "second",
                "experiment_sha256": "2" * 64,
                "status": "READY_FOR_RESEARCH_DISPATCH",
            },
        ],
    }


def test_exhaustion_is_durable_and_rotation_skips_that_neighborhood(tmp_path: Path):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "exhaustion-certificate.json").write_text(
        json.dumps({"exhausted": True, "decision": "continue_research_no_promotion"}),
        encoding="utf-8",
    )
    feedback = record_outcome(
        empty_state(),
        run=_run(),
        artifact_root=artifacts,
        stage="first",
        experiment_sha256="1" * 64,
    )
    assert feedback["outcomes"][-1]["outcome"] == "exhausted"
    plan = build_plan(_controller(), empty_rotation_state(), feedback)
    assert plan["stage"] == "second"


def test_no_candidate_is_not_falsely_marked_exhausted(tmp_path: Path):
    (tmp_path / "report.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}),
        encoding="utf-8",
    )
    feedback = record_outcome(
        empty_state(), run=_run(), artifact_root=tmp_path,
        stage="first", experiment_sha256="1" * 64,
    )
    assert feedback["outcomes"][-1]["outcome"] == "no_candidate"
    assert feedback["exhausted_experiment_sha256"] == []


def test_incomplete_run_is_rejected(tmp_path: Path):
    with pytest.raises(StrategyDiscoveryFeedbackError):
        record_outcome(
            empty_state(),
            run={"databaseId": 123, "status": "in_progress", "conclusion": None},
            artifact_root=tmp_path,
            stage="first",
            experiment_sha256="1" * 64,
        )

def test_exact_negative_fingerprint_is_not_redispatched(tmp_path: Path):
    # A workflow exit 0 with an explicit negative outcome is NOT a new strategy.
    (tmp_path / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    negative = record_outcome(
        empty_state(), run={**_run(), "headSha": "a" * 40},
        expected_source_sha="a" * 40,
        artifact_root=tmp_path, stage="first", experiment_sha256="1" * 64,
    )
    plan = build_plan(_controller(), empty_rotation_state(), negative)
    assert plan["stage"] == "second"
    assert negative["exhausted_experiment_sha256"] == []


def test_manifest_fingerprint_change_can_reopen_research(tmp_path: Path):
    (tmp_path / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    negative = record_outcome(
        empty_state(), run=_run(), artifact_root=tmp_path,
        stage="first", experiment_sha256="1" * 64,
    )
    controller = _controller()
    controller["search_stages"][0]["experiment_sha256"] = "3" * 64
    plan = build_plan(controller, empty_rotation_state(), negative)
    assert plan["stage"] == "first"


def test_all_exact_negative_static_stages_require_new_mechanism(tmp_path: Path):
    (tmp_path / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    negative = record_outcome(
        empty_state(), run=_run(), artifact_root=tmp_path,
        stage="first", experiment_sha256="1" * 64,
    )
    negative = record_outcome(
        negative, run={**_run(), "databaseId": 124}, artifact_root=tmp_path,
        stage="second", experiment_sha256="2" * 64,
    )
    with pytest.raises(Exception, match="new mechanism"):
        build_plan(_controller(), empty_rotation_state(), negative)


def test_forged_negative_feedback_digest_is_rejected(tmp_path: Path):
    (tmp_path / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    negative = record_outcome(
        empty_state(), run=_run(), artifact_root=tmp_path,
        stage="first", experiment_sha256="1" * 64,
    )
    negative["outcomes"][0]["experiment_sha256"] = "2" * 64
    with pytest.raises(Exception, match="not verified"):
        build_plan(_controller(), empty_rotation_state(), negative)


def test_successful_run_without_real_artifact_is_not_a_no_candidate(tmp_path: Path):
    with pytest.raises(StrategyDiscoveryFeedbackError, match="no readable outcome artifacts"):
        record_outcome(
            empty_state(), run=_run(), artifact_root=tmp_path,
            stage="first", experiment_sha256="1" * 64,
        )


def test_outcome_source_mismatch_fails_closed(tmp_path: Path):
    (tmp_path / "outcome.json").write_text(
        json.dumps({"decision": "continue_research_no_promotion"}), encoding="utf-8",
    )
    with pytest.raises(StrategyDiscoveryFeedbackError, match="source SHA"):
        record_outcome(
            empty_state(), run={**_run(), "headSha": "b" * 40},
            expected_source_sha="a" * 40, artifact_root=tmp_path,
            stage="first", experiment_sha256="1" * 64,
        )
