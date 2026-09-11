from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import nexus_multipair_archive_snapshot as archive_snapshot
import nexus_multipair_strategy_discovery as discovery
import nexus_multipair_training_refinement as refinement

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multipair_strategy_discovery_v2.json"
SOURCE_SHA = "a" * 40
SNAPSHOT_SHA = "b" * 64


def _summary(*, drawdown: float, good: bool = True) -> dict:
    if good:
        return {
            "count": 4,
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
        "count": 4,
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
    for timeframe in discovery.TIMEFRAME_NAMES:
        for family in discovery.FAMILIES:
            is_frontier = frontier and timeframe == "hour4" and family in {"trend_breakout", "mean_reversion"}
            summary = (
                _summary(drawdown=0.39 if family == "trend_breakout" else 0.42, good=True)
                if is_frontier else _summary(drawdown=0.65, good=False)
            )
            cells.append({
                "timeframe": timeframe,
                "family": family,
                "eligible_symbols": list(discovery.SYMBOLS),
                "variant_count": len(manifest["variants"][family]),
                "training_gate_passers": 0,
                "selected_variant_id": "fixture",
                "selected_config": _config(family),
                "selection_source": "training_only",
                "training_summary": summary,
                "training_robustness": {
                    "window_count": 2,
                    "window_policy": "overlapping_chronological_training_only",
                    "window_fraction": 0.75,
                    "all_windows_pass_training_gate": bool(is_frontier),
                    "minimum_passed_gate_count": 7 if is_frontier else 2,
                    "minimum_score": summary["score"],
                    "minimum_positive_ratio": summary["positive_ratio"],
                    "minimum_median_return": summary["median_return"],
                    "windows": [],
                },
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
        "dataset_snapshot_sha256": SNAPSHOT_SHA,
        "snapshot_schema_version": archive_snapshot.SCHEMA,
        "snapshot_data_origin": "official_public_bybit_spot_trade_archive_aggregated",
        "snapshot_runtime_freshness_claimed": False,
        "snapshot_as_of_ms": 1_800_000_000_000,
        "snapshot_history_limit": 500,
        "symbols": list(discovery.SYMBOLS),
        "timeframes": list(discovery.TIMEFRAME_NAMES),
        "families": list(discovery.FAMILIES),
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


def test_refinement_is_bounded_and_preserves_gates_costs_and_authority() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    plan, refined = refinement.build_refinement(manifest, _base_discovery())
    assert plan["should_refine"] is True
    assert plan["selection_basis"] == "training_only"
    assert plan["locked_holdout_used_for_refinement"] is False
    assert {(row["timeframe"], row["family"]) for row in plan["targeted_cells"]} == {
        ("hour4", "mean_reversion"),
        ("hour4", "trend_breakout"),
    }
    assert all("training_robustness" in row for row in plan["targeted_cells"])
    assert refined["gates"] == manifest["gates"]
    assert refined["execution"] == manifest["execution"]
    assert refined["authority"] == manifest["authority"]
    assert all(2 <= len(rows) <= refinement.MAX_VARIANTS_PER_FAMILY for rows in refined["variants"].values())
    assert plan["automatic_strategy_promotion"] is False
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


def test_non_frontier_training_evidence_does_not_expand_grid() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    plan, refined = refinement.build_refinement(manifest, _base_discovery(frontier=False))
    assert plan["should_refine"] is False
    assert plan["targeted_cells"] == []
    assert plan["variant_counts"] == {"momentum": 2, "trend_breakout": 2, "mean_reversion": 2}
    assert refined["gates"] == manifest["gates"]
    assert refined["authority"]["live_trading_authority"] is False


def test_temporal_robust_frontier_owns_family_budget() -> None:
    manifest = discovery.load_manifest(MANIFEST)
    base = _base_discovery(frontier=False)
    for cell in base["cells"]:
        if cell["family"] != "trend_breakout" or cell["timeframe"] not in {"hour1", "hour4"}:
            continue
        cell["training_summary"] = _summary(drawdown=0.10, good=True)
        if cell["timeframe"] == "hour1":
            cell["selected_config"] = {"entry_lookback": 30, "exit_lookback": 12}
            cell["training_robustness"] = {
                "window_count": 2,
                "window_policy": "overlapping_chronological_training_only",
                "window_fraction": 0.75,
                "all_windows_pass_training_gate": True,
                "minimum_passed_gate_count": 7,
                "minimum_score": 0.25,
                "minimum_positive_ratio": 0.5,
                "minimum_median_return": 0.002,
                "windows": [],
            }
        else:
            cell["selected_config"] = {"entry_lookback": 20, "exit_lookback": 10}
            cell["training_robustness"] = {
                "window_count": 2,
                "window_policy": "overlapping_chronological_training_only",
                "window_fraction": 0.75,
                "all_windows_pass_training_gate": False,
                "minimum_passed_gate_count": 5,
                "minimum_score": -0.05,
                "minimum_positive_ratio": 0.5,
                "minimum_median_return": -0.003,
                "windows": [],
            }
    _redigest(base)
    plan, refined = refinement.build_refinement(manifest, base)

    assert plan["temporal_robustness_used_for_budgeting"] is True
    assert {
        (row["timeframe"], row["family"]) for row in plan["training_frontier_cells"]
    } == {("hour1", "trend_breakout"), ("hour4", "trend_breakout")}
    assert [(row["timeframe"], row["family"]) for row in plan["targeted_cells"]] == [
        ("hour1", "trend_breakout")
    ]
    trend_variants = refined["variants"]["trend_breakout"]
    assert {"entry_lookback": 30, "exit_lookback": 12} in trend_variants
    assert {"entry_lookback": 20, "exit_lookback": 10} not in trend_variants
    assert len(trend_variants) == refinement.MAX_VARIANTS_PER_FAMILY


def test_robust_neighborhood_expands_without_exceeding_family_cap() -> None:
    base = refinement._neighborhood(  # noqa: SLF001
        "trend_breakout", {"entry_lookback": 30, "exit_lookback": 12}
    )
    robust = refinement._robust_neighborhood(  # noqa: SLF001
        "trend_breakout", {"entry_lookback": 30, "exit_lookback": 12}
    )
    assert len(robust) > len(base)
    assert len(robust) <= refinement.MAX_VARIANTS_PER_FAMILY
    assert all(row["exit_lookback"] < row["entry_lookback"] for row in robust)


def test_workflow_records_training_only_refinement_diagnostics() -> None:
    workflow = (ROOT / ".github" / "workflows" / "nexus_multipair_strategy_discovery_v2.yml").read_text(encoding="utf-8")
    assert "nexus_multipair_training_refinement" in workflow
    assert "refinement-plan.json" in workflow
    assert "locked_holdout_used_for_refinement" in workflow
    assert "refinement_targeted_cells" in workflow
    assert "automatic_strategy_promotion" in workflow
    assert "live_trading_authority" in workflow
