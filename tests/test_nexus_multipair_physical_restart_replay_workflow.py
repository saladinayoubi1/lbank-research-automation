from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_physical_restart_replay.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_restart_replay_workflow_yaml_is_valid_and_bounded() -> None:
    document = yaml.safe_load(_text())
    assert isinstance(document, dict)
    assert set(document["jobs"]) == {
        "contract-test",
        "runtime-wheelhouse",
        "seed-physical",
        "replay-physical",
        "persist-proof",
    }


def test_restart_replay_is_main_only_one_shot_and_not_scheduled() -> None:
    text = _text()
    assert "name: NEXUS Multi-Pair physical restart replay" in text
    assert "schedule:" not in text
    assert "workflow_dispatch:" in text
    assert text.count("github.event_name != 'pull_request' && github.ref == 'refs/heads/main'") == 2
    assert text.count("runs-on: nexus-bybit-network") == 2


def test_restart_replay_uses_two_independent_physical_jobs_and_external_state() -> None:
    text = _text()
    assert "  seed-physical:" in text
    assert "  replay-physical:" in text
    assert "needs: [runtime-wheelhouse, seed-physical]" in text
    assert 'state_root="$HOME/.local/share/nexus/multipair-restart-replay/$GITHUB_RUN_ID"' in text
    assert "continuity_state_storage=physical_external_runtime_path" in text
    assert "continuity_state_recovered_from_external_path=PASS" in text
    assert "physical_external_runtime_path" in text
    assert "persistent_runtime_database_on_github" in text
    assert '"persistent_runtime_database_on_github": False' in text


def test_restart_replay_requires_same_runner_exact_sha_and_bounded_fetch() -> None:
    text = _text()
    assert 'assert \'$CURRENT_RUNNER_NAME\' == \'$EXPECTED_SEED_RUNNER_NAME\'' in text
    assert text.count('git -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"') == 2
    assert text.count('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"') == 2
    assert text.count("for fetch_attempt in 1 2 3") == 2
    for section in (
        text.split("  seed-physical:", 1)[1].split("  replay-physical:", 1)[0],
        text.split("  replay-physical:", 1)[1].split("  persist-proof:", 1)[0],
    ):
        assert "uses: actions/checkout" not in section
        assert "uses: actions/upload-artifact" not in section


def test_restart_replay_proves_no_duplicate_bar_execution() -> None:
    text = _text()
    assert '--now-ms "$REPLAY_NOW_MS"' in text
    assert 'assert proof["verified_cell_count"] == 12' in text
    assert 'assert proof["blocked_cell_count"] == 0' in text
    assert 'assert proof["reported_lane_count"] == 36' in text
    assert 'assert proof["duplicate_bar_execution_count"] == 0' in text
    assert 'assert proof["skipped_no_new_bar_count"] == 12' in text
    assert 'assert proof["state_digest_preserved"] is True' in text
    assert 'assert proof["cell_cursors_preserved"] is True' in text
    assert 'assert proof["lane_identity_preserved"] is True' in text


def test_restart_replay_preserves_paper_authority_and_issue_984_isolation() -> None:
    text = _text()
    assert 'assert proof["paper_only"] is True' in text
    assert 'assert proof["live_trading_authority"] is False' in text
    assert 'assert proof["private_credentials_used"] is False' in text
    assert 'assert proof["automatic_strategy_promotion"] is False' in text
    assert 'assert proof["deterministic_risk_final_authority"] is True' in text
    assert '"state_isolated_from_issue_984": True' in text
    assert '"issue_984_state_artifact_touched": False' in text
    assert '"real_exchange_orders": False' in text
    assert "STATE_ARTIFACT: nexus-persistent-paper-trading-state" not in text
    assert "nexus-persistent-paper-trading-state" not in text
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "id-token: write" not in text


def test_restart_replay_persists_only_compact_proof() -> None:
    text = _text()
    assert 'test "${#proof_b64}" -lt 60000' in text
    assert "nexus-multipair-restart-replay-proof-${{ github.sha }}" in text
    assert "build/nexus-multipair-restart-replay-proof/evidence.json" in text
    assert 'assert evidence["duplicate_bar_execution_count"] == 0' in text
    assert 'assert evidence["skipped_no_new_bar_count"] == 12' in text
    assert 'assert evidence["state_isolated_from_issue_984"] is True' in text
    assert 'assert evidence["persistent_runtime_database_on_github"] is False' in text
