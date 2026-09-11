from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nexus_multitimeframe_strategy_discovery as discovery
import nexus_multitimeframe_training_refinement as refinement

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multitimeframe_strategy_discovery_v1.json"
SOURCE_SHA = "a" * 40


def _summary(*, drawdown: float, good: bool = True) -> dict:
    if good:
        return {
            "count": 2,
            "positive_ratio": 1.0,
            "median_return": 0.10,
            "worst_return": 0.03,
            "worst_drawdown": drawdown,
            "median_sharpe": 0.7,
            "minimum_sharpe": 0.4,
            "minimum_fill_count": 10,
            "median_turnover": 2.0,
            "score": 0.8,
        }
    return {
        "count": 2,
        "positive_ratio": 0.0,
        "median_return": -0.30,
        "worst_return": -0.40,
        "worst_drawdown": drawdown,
        "median_sharpe": -1.5,
        "minimum_sharpe": -2.0,
        "minimum_fill_count": 10,
        "median_turnover": 2.0,
        "score": -2.0,
    }


def _config(family: str) -> dict:
    if family == "momentum":
        return {"lookback": 30, "entry_threshold": 0.005}
    if family == "trend_breakout":
        return {"entry_lookback": 40, "exit_lookback": 20}
    if family == "mean_reversion":
        return {"lookback": 40, "entry_z": -2.0, "exit_z": 0.0}
    raise AssertionError(family)


def _base_discovery(*, frontier: bool = True) -> dict:
    manifest = discovery.load_manifest(MANIFEST)
    cells = []
    for timeframe in discovery.APPROVED_TIMEFRAMES:
        for family in discovery.APPROVED_FAMILIES:
            is_frontier = frontier and timeframe == "hour4" and family in {"trend_breakout", "mean_reversion"}
            summary = (
                _summary(drawdown=0.39 if family == "trend_breakout" else 0.42, good=True)
                if is_frontier else _summary(drawdown=0.65, good=False)
            )
            cells.append({
                "timeframe": timeframe,
                "family": family,
                "variant_count": len(manifest["variants"][family]),
                "training_gate_passers": 0,
                "selected_variant_id": "fixture",
                "selected_config": _config(family),
                "selection_source": "training_only",
                "training_summary": summary,
                "locked_profiles": {
                    "conservative": {"summary": _summary(drawdown=0.9, good=False), "gate_checks": {}, "passes": False},
                    "stress": {"summary": _summary(drawdown=0.95, good=False), "gate_checks": {}, "passes": False},
                },
                "proposal_eligible": False,
                "automatic_candidate_created": False,
                "automatic_paper_forward_started": False,
                "live_trading_enabled": False,
            })
    core = {
        "schema_version": discovery.SCHEMA,
        "source_sha": SOURCE_SHA,
        "experiment_id": manifest["experiment_id"],
        "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
        "symbols": list(discovery.APPROVED_SYMBOLS),
        "timeframes": list(discovery.APPROVED_TIMEFRAMES),
        "families": list(discovery.APPROVED_FAMILIES),
        "hypothesis_count": 9,
        "selection_policy": "training only fixture",
        "multiplicity_policy": "fixture",
        "cells": sorted(cells, key=lambda row: (row["timeframe"], row["family"])),
        "research_proposals": [],
        "research_proposal_count": 0,
        "research_only": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "automatic_paper_forward_started": False,
    }
    return {**core, "discovery_digest": discovery._digest(core)}  # noqa: SLF001


def _redigest(value: dict) -> None:
    core = dict(value)
    core.pop("discovery_digest", None)
    value["discovery_digest"] = discovery._digest(core)  # noqa: SLF001


def test_refinement_is_bounded_and_preserves_gates_and_authority() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    plan, refined = refinement.build_refinement(manifest, _base_discovery())

    assert plan["should_refine"] is True
    assert plan["selection_basis"] == "training_only"
    assert plan["locked_holdout_used_for_refinement"] is False
    assert {(row["timeframe"], row["family"]) for row in plan["targeted_cells"]} == {
        ("hour4", "mean_reversion"),
        ("hour4", "trend_breakout"),
    }
    assert refined["gates"] == manifest["gates"]
    assert refined["authority"] == manifest["authority"]
    assert all(2 <= len(rows) <= refinement.MAX_VARIANTS_PER_FAMILY for rows in refined["variants"].values())
    assert plan["automatic_strategy_promotion"] is False
    assert plan["automatic_paper_forward_started"] is False
    assert plan["live_trading_authority"] is False


def test_locked_holdout_mutation_cannot_change_refinement_manifest() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    baseline = _base_discovery()
    mutated = deepcopy(baseline)
    for cell in mutated["cells"]:
        cell["locked_profiles"] = {"tampered": {"summary": {"future": 999999}, "passes": True}}
    _redigest(mutated)
    assert discovery.verify_discovery(mutated)["decision"] == "pass"

    first_plan, first_manifest = refinement.build_refinement(manifest, baseline)
    second_plan, second_manifest = refinement.build_refinement(manifest, mutated)

    assert first_manifest == second_manifest
    assert first_plan["training_basis_digest"] == second_plan["training_basis_digest"]
    assert first_plan["source_discovery_digest"] != second_plan["source_discovery_digest"]


def test_non_frontier_training_evidence_stays_bounded_without_refinement() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    plan, refined = refinement.build_refinement(manifest, _base_discovery(frontier=False))

    assert plan["should_refine"] is False
    assert plan["targeted_cells"] == []
    assert plan["variant_counts"] == {"momentum": 2, "trend_breakout": 2, "mean_reversion": 2}
    assert refined["gates"] == manifest["gates"]
    assert refined["authority"]["live_trading_authority"] is False


def test_nonzero_proposal_base_does_not_launch_refinement() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    base = _base_discovery()
    proposal_core = {
        "proposal_state": "RESEARCH_PROPOSAL",
        "family": "trend_breakout",
        "timeframe": "hour4",
        "strategy_config": {"entry_lookback": 40, "exit_lookback": 20},
        "variant_id": "fixture",
        "cell_digest": "fixture",
        "dataset_archive_sha256": manifest["dataset"]["archive_sha256"],
        "requires_independent_runtime_requalification": True,
        "paper_only": True,
        "live_trading_authority": False,
        "promotion_authority": False,
    }
    base["research_proposals"] = [
        {**proposal_core, "proposal_digest": discovery._digest(proposal_core)}  # noqa: SLF001
    ]
    base["research_proposal_count"] = 1
    _redigest(base)
    assert discovery.verify_discovery(base)["decision"] == "pass"

    plan, refined = refinement.build_refinement(manifest, base)

    assert plan["base_research_proposal_count"] == 1
    assert plan["should_refine"] is False
    assert plan["targeted_cells"] == []
    assert refined["authority"] == manifest["authority"]


def test_workflow_runs_training_only_refinement_without_live_authority() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "nexus_multitimeframe_strategy_discovery.yml"
    ).read_text(encoding="utf-8")
    assert "nexus_multitimeframe_training_refinement.py" in workflow
    assert "refinement-plan.json" in workflow
    assert "refinement-manifest.json" in workflow
    assert "locked_holdout_used_for_refinement" in workflow
    assert "automatic_strategy_promotion" in workflow
    assert "live_trading_authority" in workflow
