from __future__ import annotations

from pathlib import Path

import yaml

import nexus_multipair_recent_archive_runtime_snapshot as recent


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_archive_snapshot.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _physical_section() -> str:
    text = _text()
    return text.split("  contract-test:", 1)[1]


def test_archive_acceptance_workflow_keeps_policy_job_inventory_and_read_only_permissions() -> None:
    value = yaml.safe_load(_text())
    assert set(value["jobs"]) == {"acquire-snapshot", "contract-test"}
    assert value["permissions"] == {"actions": "read", "contents": "read"}


def test_recent_artifact_inner_archive_matches_consumer_contract() -> None:
    text = _text()
    canonical = "build/nexus-multipair-runtime-requalification-snapshot.zip"
    assert f"--archive-output {canonical}" in text
    assert text.count(canonical) == 2
    assert "--archive-output build/nexus-multipair-recent-runtime-snapshot.zip" not in text


def test_physical_requalification_uses_bounded_extended_transport_window() -> None:
    physical = _physical_section()
    physical_window_ms = 2_700_000
    assert f"--max-transport-age-ms {physical_window_ms}" in physical
    assert recent.MAX_TRANSPORT_AGE_MS < physical_window_ms < recent.MAX_SOURCE_LAG_MS


def test_physical_acceptance_uses_no_javascript_artifact_action() -> None:
    physical = _physical_section()
    assert "actions/download-artifact" not in physical
    assert "actions/upload-artifact" not in physical
    assert "scripts/nexus_public_current_run_artifact.py wheelhouse" in physical
    assert "scripts/nexus_public_current_run_artifact.py historical" in physical
    assert "scripts/nexus_public_current_run_artifact.py recent" in physical
    assert "multipair_final_acceptance_javascript_artifact_actions=false" in physical


def test_public_artifact_transport_is_digest_exact_run_and_read_token_bound() -> None:
    physical = _physical_section()
    assert 'GH_TOKEN: ${{ github.token }}' in physical
    assert '--run-id "$GITHUB_RUN_ID"' in physical
    assert '--source-sha "$GITHUB_SHA"' in physical
    assert '--expected-sha256 "$EXPECTED_WHEELHOUSE_SHA256"' in physical
    assert '--expected-sha256 "$EXPECTED_HISTORICAL_ARCHIVE_SHA256"' in physical
    assert '--expected-snapshot-digest "$EXPECTED_HISTORICAL_SNAPSHOT_DIGEST"' in physical
    assert '--expected-sha256 "$EXPECTED_RECENT_ARCHIVE_SHA256"' in physical
    assert '--expected-snapshot-digest "$EXPECTED_RECENT_SNAPSHOT_DIGEST"' in physical
    assert '--expected-acquired-at-ms "$EXPECTED_RECENT_ACQUIRED_AT_MS"' in physical
    assert '--expected-data-as-of-ms "$EXPECTED_RECENT_DATA_AS_OF_MS"' in physical


def test_final_proof_preserves_authority_and_issue_984_boundaries() -> None:
    physical = _physical_section()
    assert '"paper_runtime_cells": 12' in physical
    assert '"paper_runtime_lanes": 36' in physical
    assert '"runtime_snapshot_distinct_from_discovery": True' in physical
    assert '"historical_discovery_snapshot_reused": False' in physical
    assert '"research_only": True' in physical
    assert '"paper_execution_started": False' in physical
    assert '"live_trading_authority": False' in physical
    assert '"private_credentials_used": False' in physical
    assert '"real_exchange_orders": False' in physical
    assert '"automatic_strategy_promotion": False' in physical
    assert '"deterministic_risk_final_authority": True' in physical
    assert '"issue_984_state_touched": False' in physical
    assert '"persistent_runtime_database_on_github": False' in physical
    assert "multipair_final_physical_acceptance=PASS" in physical
