from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multipair_strategy_discovery_v2.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _section(text: str, job: str, next_job: str) -> str:
    return text.split(f"  {job}:", 1)[1].split(f"  {next_job}:", 1)[0]


def test_discovery_v2_workflow_yaml_is_valid_and_has_exact_jobs() -> None:
    document = yaml.safe_load(_text())
    assert isinstance(document, dict)
    assert set(document["jobs"]) == {
        "contract-test",
        "runtime-wheelhouse",
        "discover-physical",
        "requalify-physical",
        "persist-proof",
    }


def test_discovery_v2_is_one_shot_read_only_and_not_scheduled() -> None:
    text = _text()
    assert "name: NEXUS Multi-Pair Discovery v2 physical proof" in text
    assert "schedule:" not in text
    assert "workflow_dispatch:" in text
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "contents: write" not in text
    assert "actions: write" not in text
    assert "id-token: write" not in text


def test_contract_gate_covers_archive_dispatch_and_transport() -> None:
    contract = _section(_text(), "contract-test", "runtime-wheelhouse")
    assert "tests/test_nexus_multipair_strategy_discovery.py" in contract
    assert "tests/test_nexus_multipair_strategy_discovery_archive.py" in contract
    assert "tests/test_nexus_multipair_archive_snapshot.py" in contract
    assert "tests/test_nexus_snapshot_artifact.py" in contract
    assert "tests/test_nexus_multipair_strategy_discovery_workflow.py" in contract


def test_hosted_job_builds_wheelhouse_and_immutable_official_archive_snapshot() -> None:
    hosted = _section(_text(), "runtime-wheelhouse", "discover-physical")
    assert "runs-on: ubuntu-latest" in hosted
    assert "timeout-minutes: 35" in hosted
    assert "snapshot_archive_sha256:" in hosted
    assert "snapshot_digest:" in hosted
    assert "python nexus_multipair_archive_snapshot.py" in hosted
    assert '--source-sha "$GITHUB_SHA"' in hosted
    assert '--archive-output "$archive"' in hosted
    assert "nexus-multipair-discovery-v2-archive-snapshot-${{ github.sha }}" in hosted
    assert "path: build/nexus-multipair-archive-snapshot.zip" in hosted
    assert "hosted_official_bybit_archive_snapshot=PASS" in hosted
    assert 'rm -rf "$acquire_site" "$state" "$cache" "$snapshot"' in hosted


def test_physical_jobs_are_main_only_exact_source_and_native() -> None:
    text = _text()
    discover = _section(text, "discover-physical", "requalify-physical")
    requalify = _section(text, "requalify-physical", "persist-proof")
    for section in (discover, requalify):
        assert "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'" in section
        assert "runs-on: nexus-bybit-network" in section
        assert 'git -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"' in section
        assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in section
        assert "for fetch_attempt in 1 2 3" in section
        assert "uses: actions/checkout" not in section
        assert "uses: actions/setup-python" not in section
        assert "uses: actions/upload-artifact" not in section
    assert "assert '$CURRENT_RUNNER_NAME' == '$EXPECTED_DISCOVERY_RUNNER_NAME'" in requalify


def test_discovery_v2_uses_safe_external_ephemeral_state_and_canonical_wheelhouse() -> None:
    text = _text()
    expected_root = '$HOME/.local/share/nexus/multipair-discovery-v2/$GITHUB_RUN_ID'
    assert text.count(expected_root) >= 2
    assert '"$HOME"/.local/share/nexus/multipair-discovery-v2/*)' in text
    assert "multipair_discovery_state_storage=physical_external_ephemeral_path" in text
    assert "multipair_discovery_state_recovered_from_external_path=PASS" in text
    assert "--output build/nexus-paper-runtime-wheelhouse.zip" in text
    assert "path: build/nexus-paper-runtime-wheelhouse.zip" in text
    assert 'cmp requirements.lock "$state_root/requirements.lock"' in text
    assert 'rm -rf "$STATE_ROOT"' in text


def test_physical_python_bootstrap_uses_bundled_pip_for_install_and_check() -> None:
    text = _text()
    discover = _section(text, "discover-physical", "requalify-physical")
    requalify = _section(text, "requalify-physical", "persist-proof")
    assert 'bundled = Path(ensurepip.__file__).resolve().parent / "_bundled"' in discover
    assert 'PYTHONPATH="$pip_wheel" "$PYTHON_BIN" -m pip install' in discover
    assert "printf 'PYTHONPATH=%s:%s\\n' \"$pip_wheel\" \"$runtime_site\" >> \"$GITHUB_ENV\"" in discover
    assert "name: Verify isolated runtime dependency consistency" in discover
    assert 'bundled = Path(ensurepip.__file__).resolve().parent / "_bundled"' in requalify
    assert 'test -f "$pip_wheel"' in requalify
    assert "printf 'PYTHONPATH=%s:%s\\n' \"$pip_wheel\" \"$state_root/runtime-site\" >> \"$GITHUB_ENV\"" in requalify
    assert "name: Verify recovered isolated runtime dependency consistency" in requalify


def test_discover_job_restores_and_independently_verifies_exact_archive_snapshot() -> None:
    discover = _section(_text(), "discover-physical", "requalify-physical")
    assert "scripts/nexus_snapshot_artifact.py" in discover
    assert '--expected-source-sha "$GITHUB_SHA"' in discover
    assert '--expected-snapshot-digest "$EXPECTED_HOSTED_SNAPSHOT_DIGEST"' in discover
    assert '--destination "$STATE_ROOT/snapshot"' in discover
    assert "from nexus_multipair_archive_snapshot import verify_snapshot" in discover
    assert "collect_snapshot" not in discover
    assert 'assert snapshot["cell_count"] == 12' in discover
    assert 'assert snapshot["symbols"] == list(SYMBOLS)' in discover
    assert 'assert snapshot["timeframes"] == list(TIMEFRAMES)' in discover
    assert 'assert snapshot["data_origin"] == "official_public_bybit_spot_trade_archive_aggregated"' in discover
    assert 'assert snapshot["runtime_freshness_claimed"] is False' in discover
    assert 'assert snapshot["real_exchange_orders"] is False' in discover
    assert 'assert snapshot["third_party_proxy_used"] is False' in discover
    assert 'assert result["snapshot_runtime_freshness_claimed"] is False' in discover
    assert 'assert result["hypothesis_count"] == 9' in discover
    assert 'assert len(result["cells"]) == 9' in discover
    assert 'assert all(row["selection_source"] == "training_only" for row in result["cells"])' in discover


def test_requalification_remains_separate_fresh_fail_closed_and_non_promoting() -> None:
    requalify = _section(_text(), "requalify-physical", "persist-proof")
    assert "needs: discover-physical" in requalify
    assert "nexus_multipair_strategy_proposal_requalification import run, verify_requalification" in requalify
    assert 'assert result["blocked_runtime_data_count"] == 0' in requalify
    assert 'assert result["status"] in {"NO_WORK", "EVALUATED"}' in requalify
    assert 'assert result["runtime_data_is_fresh_not_snapshot_reuse"] is True' in requalify
    assert 'assert result["candidate_creation_authority"] is False' in requalify
    assert 'assert result["paper_execution_started"] is False' in requalify
    assert 'assert result["automatic_strategy_promotion"] is False' in requalify
    assert 'assert result["live_trading_authority"] is False' in requalify
    assert 'assert result["private_credentials_used"] is False' in requalify
    assert 'assert result["deterministic_risk_final_authority"] is True' in requalify


def test_persisted_proof_records_historical_archive_without_freshness_escalation() -> None:
    text = _text()
    assert '"symbols": list(SYMBOLS)' in text
    assert '"timeframes": list(TIMEFRAMES)' in text
    assert '"families": list(FAMILIES)' in text
    assert '"snapshot_transport": "digest_pinned_current_run_github_artifact"' in text
    assert '"snapshot_data_origin": snapshot["data_origin"]' in text
    assert '"snapshot_runtime_freshness_claimed": snapshot["runtime_freshness_claimed"]' in text
    assert '"snapshot_as_of_ms": discovery["snapshot_as_of_ms"]' in text
    assert '"zero_proposal_result_is_valid": True' in text
    assert '"real_exchange_orders": False' in text
    assert '"state_isolated_from_issue_984": True' in text
    assert '"issue_984_state_artifact_touched": False' in text
    assert '"persistent_runtime_database_on_github": False' in text
    assert '"legacy_btc_eth_discovery_archive_used": False' in text
    assert "nexus-persistent-paper-trading-state" not in text
    assert "nexus-multipair-discovery-v2-proof-${{ github.sha }}" in text
    assert "build/nexus-multipair-discovery-v2-proof/evidence.json" in text
    assert 'test "${#proof_b64}" -lt 60000' in text
