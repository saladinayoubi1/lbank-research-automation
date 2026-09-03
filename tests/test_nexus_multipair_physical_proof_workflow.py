from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_physical_proof.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_physical_proof_is_main_only_one_shot_and_not_scheduled() -> None:
    text = _text()
    assert "name: NEXUS Multi-Pair physical Paper proof" in text
    assert "schedule:" not in text
    assert "workflow_dispatch:" in text
    assert "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'" in text
    assert "runs-on: nexus-bybit-network" in text
    assert "multipair_execution_plane=self-hosted:nexus-bybit-network" in text


def test_physical_proof_requires_exact_four_symbol_surface() -> None:
    text = _text()
    assert 'assert snapshot["status"] == "VERIFIED"' in text
    assert 'assert snapshot["expected_cell_count"] == 12' in text
    assert 'assert snapshot["verified_cell_count"] == 12' in text
    assert 'assert snapshot["blocked_cell_count"] == 0' in text
    assert 'assert snapshot["expected_lane_count"] == 36' in text
    assert 'assert snapshot["reported_lane_count"] == 36' in text
    assert '["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]' in text
    assert '["minute15", "hour1", "hour4"]' in text
    assert '["momentum", "trend_breakout", "mean_reversion"]' in text


def test_physical_proof_preserves_paper_only_authority() -> None:
    text = _text()
    assert 'assert snapshot["paper_only"] is True' in text
    assert 'assert snapshot["live_trading_authority"] is False' in text
    assert 'assert snapshot["private_credentials_used"] is False' in text
    assert 'assert snapshot["automatic_strategy_promotion"] is False' in text
    assert 'assert snapshot["deterministic_risk_final_authority"] is True' in text
    assert '"real_exchange_orders": False' in text
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "id-token: write" not in text


def test_physical_proof_is_storage_isolated_from_issue_984() -> None:
    text = _text()
    assert '"state_isolated_from_issue_984": True' in text
    assert '"issue_984_state_artifact_name": "nexus-persistent-paper-trading-state"' in text
    assert '"persistent_state_enabled": False' in text
    assert "STATE_ARTIFACT: nexus-persistent-paper-trading-state" not in text
    assert "nexus-multipair-physical-proof-${{ github.sha }}" in text
    assert "nexus-multipair-physical-proof/evidence.json" in text


def test_physical_job_uses_exact_source_native_checkout_and_bounded_fetch() -> None:
    text = _text()
    assert 'git -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"' in text
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in text
    assert "for fetch_attempt in 1 2 3" in text
    physical_section = text.split("  physical-proof:", 1)[1].split("  persist-proof:", 1)[0]
    assert "uses: actions/checkout" not in physical_section
    assert "uses: actions/upload-artifact" not in physical_section
