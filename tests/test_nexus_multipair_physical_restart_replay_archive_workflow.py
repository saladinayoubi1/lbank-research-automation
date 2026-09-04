from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_physical_restart_replay_archive.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _physical(text: str) -> tuple[str, str]:
    seed = text.split("  seed-physical:", 1)[1].split("  replay-physical:", 1)[0]
    replay = text.split("  replay-physical:", 1)[1].split("  persist-proof:", 1)[0]
    return seed, replay


def test_recent_archive_restart_workflow_is_bounded_main_only_and_read_only() -> None:
    text = _text()
    value = yaml.safe_load(text)
    assert isinstance(value, dict)
    assert set(value["jobs"]) == {
        "contract-test",
        "acquire-runtime",
        "seed-physical",
        "replay-physical",
        "persist-proof",
    }
    assert value["permissions"] == {"contents": "read"}
    assert "schedule:" not in text
    assert "workflow_dispatch:" in text
    assert text.count("runs-on: nexus-bybit-network") == 2
    assert text.count("github.event_name != 'pull_request' && github.ref == 'refs/heads/main'") == 3


def test_recent_archive_restart_uses_official_snapshot_and_exact_public_transport() -> None:
    text = _text()
    assert "nexus_multipair_recent_archive_runtime_snapshot.py acquire" in text
    assert "build/nexus-multipair-runtime-requalification-snapshot.zip" in text
    assert "build/nexus-multipair-recent-runtime-snapshot.sha256" in text
    assert "scripts/nexus_public_current_run_artifact.py recent" in text
    assert '--expected-snapshot-digest "$EXPECTED_RECENT_SNAPSHOT_DIGEST"' in text
    assert '--expected-acquired-at-ms "$EXPECTED_RECENT_ACQUIRED_AT_MS"' in text
    assert '--expected-data-as-of-ms "$EXPECTED_RECENT_DATA_AS_OF_MS"' in text
    assert "runtime_requalification_recency_verified" in text
    assert 'live_freshness_claimed"] is False' in text


def test_both_physical_jobs_are_node_free_and_exact_source_bound() -> None:
    text = _text()
    seed, replay = _physical(text)
    for section in (seed, replay):
        assert "uses:" not in section
        assert "actions/download-artifact" not in section
        assert "actions/upload-artifact" not in section
        assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in section
        assert "for attempt in 1 2 3" in section
        assert "scripts/nexus_public_current_run_artifact.py wheelhouse" in section
    assert "continuity_physical_javascript_artifact_actions=false" in seed
    assert "EXPECTED_SEED_RUNNER_NAME" in replay
    assert "assert '$CURRENT_RUNNER_NAME' == '$EXPECTED_SEED_RUNNER_NAME'" in replay


def test_seed_and_replay_use_archive_paper_adapter_not_direct_rest_matrix() -> None:
    text = _text()
    seed, replay = _physical(text)
    assert "nexus_multipair_recent_archive_paper_matrix.py" in seed
    assert "nexus_multipair_recent_archive_paper_matrix.py" in replay
    assert "nexus_multipair_demo_strategy_matrix.py \\" not in seed
    assert "nexus_multipair_demo_strategy_matrix.py \\" not in replay
    assert '"direct_bybit_rest_used_on_physical_runner": False' in replay
    assert '"runtime_data_transport": recent.TRANSPORT_ORIGIN' in replay
    assert '"runtime_live_freshness_claimed": False' in replay


def test_restart_proof_requires_12_cells_36_lanes_and_no_duplicate_bar() -> None:
    text = _text()
    assert 'assert proof["verified_cell_count"] == 12' in text
    assert 'assert proof["blocked_cell_count"] == 0' in text
    assert 'assert proof["reported_lane_count"] == 36' in text
    assert 'assert proof["duplicate_bar_execution_count"] == 0' in text
    assert 'assert proof["skipped_no_new_bar_count"] == 12' in text
    assert 'assert proof["state_digest_preserved"] is True' in text
    assert 'assert proof["cell_cursors_preserved"] is True' in text
    assert 'assert proof["lane_identity_preserved"] is True' in text
    assert "NEXUS_RESTART_REPLAY_PROOF_SHA256=" in text
    assert "NEXUS_RESTART_REPLAY_PROOF_BASE64=" in text


def test_restart_proof_preserves_authority_and_issue_984_isolation() -> None:
    text = _text()
    assert 'assert proof["paper_only"] is True' in text
    assert 'assert proof["live_trading_authority"] is False' in text
    assert 'assert proof["private_credentials_used"] is False' in text
    assert 'assert proof["automatic_strategy_promotion"] is False' in text
    assert 'assert proof["deterministic_risk_final_authority"] is True' in text
    assert '"state_isolated_from_issue_984": True' in text
    assert '"issue_984_state_artifact_touched": False' in text
    assert '"real_exchange_orders": False' in text
    assert '"persistent_runtime_database_on_github": False' in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "id-token: write" not in text
