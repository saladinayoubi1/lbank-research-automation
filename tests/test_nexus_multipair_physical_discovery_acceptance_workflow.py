from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_physical_discovery_acceptance.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_physical_discovery_workflow_yaml_is_valid_and_bounded() -> None:
    document = yaml.safe_load(_text())
    assert isinstance(document, dict)
    assert set(document["jobs"]) == {
        "contract-test",
        "runtime-wheelhouse",
        "physical-discovery",
        "persist-proof",
    }


def test_physical_discovery_is_main_only_one_shot_and_not_scheduled() -> None:
    text = _text()
    assert "name: NEXUS Multi-Pair physical Discovery acceptance" in text
    assert "schedule:" not in text
    assert "workflow_dispatch:" in text
    assert text.count("github.event_name != 'pull_request' && github.ref == 'refs/heads/main'") == 1
    assert text.count("runs-on: nexus-bybit-network") == 1


def test_physical_discovery_job_has_no_javascript_actions_and_uses_exact_sha() -> None:
    text = _text()
    physical = text.split("  physical-discovery:", 1)[1].split("  persist-proof:", 1)[0]
    assert "uses: actions/checkout" not in physical
    assert "uses: actions/setup-python" not in physical
    assert "uses: actions/upload-artifact" not in physical
    assert 'git -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"' in physical
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in physical
    assert "for fetch_attempt in 1 2 3" in physical
    assert "RUNNER_NAME_EVIDENCE: ${{ runner.name }}" in physical
    assert "RUNNER_OS_EVIDENCE: ${{ runner.os }}" in physical
    assert "RUNNER_ENVIRONMENT_EVIDENCE: ${{ runner.environment }}" in physical


def test_physical_discovery_uses_isolated_external_state_and_never_issue_984_artifact() -> None:
    text = _text()
    assert 'state_root="$HOME/.local/share/nexus/multipair-discovery-acceptance/$GITHUB_RUN_ID"' in text
    assert "discovery_state_storage=physical_external_runtime_path" in text
    assert "nexus-persistent-paper-trading-state" not in text
    assert '"state_isolated_from_issue_984": True' not in text  # proof is produced by the verifier module, not forged inline
    assert '"issue_984_state_artifact_touched": False' not in text
    assert 'assert value["state_isolated_from_issue_984"] is True' not in text
    assert '"state_isolated_from_issue_984"' in text
    assert '"issue_984_state_artifact_touched"' in text


def test_physical_discovery_restores_canonical_digest_pinned_wheelhouse() -> None:
    text = _text()
    assert "--output build/nexus-paper-runtime-wheelhouse.zip" in text
    assert "path: build/nexus-paper-runtime-wheelhouse.zip" in text
    assert "restore-current-run" in text
    assert '--expected-sha256 "$WHEELHOUSE_ARCHIVE_SHA256"' in text
    assert "--repository-lock requirements.lock" in text
    assert "--no-index" in text


def test_physical_discovery_executes_real_four_symbol_discovery_and_requalification() -> None:
    text = _text()
    assert "nexus_multipair_physical_discovery_acceptance.py" in text
    assert "experiments/nexus_multipair_strategy_discovery_v2.json" in text
    assert "--execution-plane nexus-bybit-network" in text
    assert "--history-limit 240" in text
    assert 'value.get("symbols") != ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"]' in text
    assert 'value.get("timeframes") != ["minute15", "hour1", "hour4"]' in text
    assert 'value.get("families") != ["momentum", "trend_breakout", "mean_reversion"]' in text
    assert 'value.get("snapshot_cell_count") != 12' in text
    assert 'value.get("hypothesis_count") != 9' in text
    assert 'value.get("blocked_runtime_data_count") != 0' in text


def test_physical_discovery_preserves_research_and_paper_authority_boundaries() -> None:
    text = _text()
    assert "training_selection_only" in text
    assert "locked_holdout_after_selection" in text
    assert "conservative_and_stress_costs" in text
    assert "zero_proposals_valid" in text
    assert "research_proposal_only" in text
    assert "fresh_runtime_requalification" in text
    assert "candidate_state_created" in text
    assert "paper_execution_started" in text
    assert "automatic_strategy_promotion" in text
    assert "live_trading_authority" in text
    assert "private_credentials_used" in text
    assert "real_exchange_orders" in text
    assert "deterministic_risk_final_authority" in text
    assert "silent_exchange_substitution" in text
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "id-token: write" not in text


def test_physical_discovery_persists_only_compact_proof() -> None:
    text = _text()
    assert 'test "${#proof_b64}" -lt 60000' in text
    assert "nexus-multipair-physical-discovery-proof-${{ github.sha }}" in text
    assert "build/nexus-multipair-physical-discovery-proof/evidence.json" in text
    persist = text.split("  persist-proof:", 1)[1]
    assert "nexus_multipair_discovery_snapshot" not in persist
    assert "research_proposals.json" not in persist
    assert "requalification/result.json" not in persist
    assert 'assert value["research_proposal_count"] == value["requalification_proposal_count"]' in persist
    assert 'assert value["blocked_runtime_data_count"] == 0' in persist
