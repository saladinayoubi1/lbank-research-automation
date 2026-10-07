from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import nexus_strategy_discovery_controller as controller


def _materialize_minimal_surface(root: Path) -> None:
    catalog = {
        "schema": "nexus.strategy-family-catalog.v1",
        "status": "research-only",
        "paper_trading_only": True,
        "families": [
            {
                "family": "trend",
                "markets": ["crypto"],
                "hypothesis": "bounded test",
                "evidence": [],
                "critical_risks": [],
                "falsification": "fail out of sample",
                "paper_gate": "paper only",
            },
            {
                "family": "momentum",
                "markets": ["crypto"],
                "hypothesis": "bounded test",
                "evidence": [],
                "critical_risks": [],
                "falsification": "fail out of sample",
                "paper_gate": "paper only",
            },
        ],
    }
    catalog_path = root / controller.CATALOG_PATH
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    for spec in controller.SEARCH_STAGES:
        engine = root / spec["engine"]
        engine.parent.mkdir(parents=True, exist_ok=True)
        engine.write_text("# bounded research engine fixture\n", encoding="utf-8")

        experiment = root / spec["experiment"]
        experiment.parent.mkdir(parents=True, exist_ok=True)
        experiment.write_text(
            json.dumps({"schema_version": 1, "experiment_id": f"{spec['stage']}_fixture"}),
            encoding="utf-8",
        )

        workflow = root / spec["workflow"]
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text("name: fixture\non:\n  workflow_dispatch:\n", encoding="utf-8")

    for paths in controller.FRONTIER_FINGERPRINT_INPUTS.values():
        for relative in paths:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_text(f"# fingerprint fixture: {relative}\n", encoding="utf-8")


def test_repository_discovery_surface_is_bounded_and_ready() -> None:
    status = controller.build_status(ROOT)

    assert status["controller_verified"] is True
    assert status["mode"] == "research-backtest-paper-only"
    assert status["paper_only"] is True
    assert status["live_trading_authority"] is False
    assert status["summary"]["strategy_family_count"] >= 1
    assert status["summary"]["search_stage_count"] == len(controller.SEARCH_STAGES)
    assert status["summary"]["ready_search_stage_count"] == len(controller.SEARCH_STAGES)
    assert status["qualified_candidates"] == []
    assert status["qualification_claimed"] is False
    assert all(row["status"] == "READY_FOR_RESEARCH_DISPATCH" for row in status["search_stages"])
    assert all(row["dispatch_mode"] == "reviewed_workflow_dispatch" for row in status["search_stages"])
    frontier = [row for row in status["search_stages"] if row["rotation_eligible"] is True]
    legacy = [row for row in status["search_stages"] if row["lane"] == "legacy_validation"]
    assert [row["stage"] for row in frontier] == [
        "nexus_multitimeframe_strategy_discovery",
        "nexus_multipair_strategy_discovery_v2",
    ]
    assert len(legacy) == 6
    assert all(row["rotation_eligible"] is False for row in legacy)
    assert status["summary"]["ready_frontier_stage_count"] == 2
    assert status["summary"]["ready_legacy_validation_stage_count"] == 6
    assert status["next_research_action"] == "nexus_multitimeframe_strategy_discovery"


def test_composite_frontier_fingerprint_changes_without_rewriting_base_manifest(tmp_path: Path) -> None:
    _materialize_minimal_surface(tmp_path)
    first = controller.build_status(tmp_path)
    first_stage = next(
        row for row in first["search_stages"]
        if row["stage"] == "nexus_multitimeframe_strategy_discovery"
    )
    manifest_sha = first_stage["experiment_sha256"]

    mechanism = tmp_path / "nexus_mechanism_factory.py"
    mechanism.write_text("# changed reviewed mechanism frontier\n", encoding="utf-8")

    second = controller.build_status(tmp_path)
    second_stage = next(
        row for row in second["search_stages"]
        if row["stage"] == "nexus_multitimeframe_strategy_discovery"
    )
    assert second_stage["experiment_sha256"] == manifest_sha
    assert second_stage["frontier_sha256"] != first_stage["frontier_sha256"]
    assert second["controller_verified"] is True


def test_missing_engine_fails_visible_and_never_qualifies_candidate(tmp_path: Path) -> None:
    _materialize_minimal_surface(tmp_path)
    missing = tmp_path / controller.SEARCH_STAGES[2]["engine"]
    missing.unlink()

    status = controller.build_status(tmp_path)

    assert status["controller_verified"] is False
    assert status["live_trading_authority"] is False
    assert status["qualified_candidates"] == []
    assert status["qualification_claimed"] is False
    assert status["next_research_action"] == "repair_discovery_surface_before_dispatch"
    assert any("missing_engine" in error for error in status["errors"])
    blocked = [row for row in status["search_stages"] if row["status"] == "BLOCKED"]
    assert len(blocked) == 1
    assert blocked[0]["stage"] == controller.SEARCH_STAGES[2]["stage"]


def test_non_paper_catalog_fails_closed(tmp_path: Path) -> None:
    _materialize_minimal_surface(tmp_path)
    catalog_path = tmp_path / controller.CATALOG_PATH
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["paper_trading_only"] = False
    catalog_path.write_text(json.dumps(catalog), encoding="utf-8")

    status = controller.build_status(tmp_path)

    assert status["controller_verified"] is False
    assert "strategy_family_catalog_not_paper_only" in status["errors"]
    assert status["paper_only"] is True
    assert status["live_trading_authority"] is False
    assert status["qualified_candidates"] == []


def test_status_digest_is_deterministic(tmp_path: Path) -> None:
    _materialize_minimal_surface(tmp_path)

    first = controller.build_status(tmp_path)
    second = controller.build_status(tmp_path)

    assert first == second
    assert len(first["status_sha256"]) == 64
