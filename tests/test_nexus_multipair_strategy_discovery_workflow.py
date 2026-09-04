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
        "runtime-snapshot",
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


def test_contract_gate_covers_archive_dispatch_transport_and_fresh_requalification() -> None:
    contract = _section(_text(), "contract-test", "runtime-wheelhouse")
    assert "tests/test_nexus_multipair_strategy_discovery.py" in contract
    assert "tests/test_nexus_multipair_strategy_discovery_archive.py" in contract
    assert "tests/test_nexus_multipair_archive_snapshot.py" in contract
    assert "tests/test_nexus_snapshot_artifact.py" in contract
    assert "tests/test_nexus_multipair_runtime_requalification_snapshot.py" in contract
    assert "tests/test_nexus_multipair_runtime_requalification_snapshot_contract.py" in contract
    assert "tests/test_nexus_runtime_snapshot_artifact.py" in contract
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


def test_fresh_runtime_snapshot_is_acquired_hosted_only_after_historical_discovery() -> None:
    runtime = _section(_text(), "runtime-snapshot", "requalify-physical")
    assert "needs: discover-physical" in runtime
    assert "runs-on: ubuntu-latest" in runtime
    assert "timeout-minutes: 20" in runtime
    assert "python -m pip install -r requirements.lock" in runtime
    assert "python nexus_multipair_runtime_requalification_snapshot.py acquire" in runtime
    assert '--source-sha "$GITHUB_SHA"' in runtime
    assert '--now-ms "$now_ms"' in runtime
    assert "runtime_snapshot_digest:" in runtime
    assert "runtime_snapshot_as_of_ms:" in runtime
    assert "runtime_snapshot_archive_sha256:" in runtime
    assert "nexus-multipair-runtime-requalification-snapshot-${{ github.sha }}" in runtime
    assert "path: build/nexus-multipair-runtime-requalification-snapshot.zip" in runtime
    assert "hosted_fresh_multipair_runtime_snapshot=PASS" in runtime


def test_physical_jobs_are_main_only_exact_source_and_native() -> None:
    text = _text()
    discover = _section(text, "discover-physical", "runtime-snapshot")
    requalify = _section(text, "requalify-physical", "persist-proof")
    for section in (discover, requalify):
        assert "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'" in section
        assert "runs-on: nexus-bybit-network" in section
        assert "uses: actions/checkout" not in section
        assert "uses: actions/setup-python" not in section
        assert "uses: actions/upload-artifact" not in section
    assert 'git -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"' in discover
    assert 'test "$(git rev-parse HEAD)" = "$GITHUB_SHA"' in discover
    assert "for fetch_attempt in 1 2 3" in discover
    assert 'git -C "$source_root" -c http.version=HTTP/1.1 fetch --no-tags --prune --depth=1 origin "$GITHUB_SHA"' in requalify
    assert 'test "$(git -C "$source_root" rev-parse HEAD)" = "$GITHUB_SHA"' in requalify
    assert "for fetch_attempt in 1 2 3" in requalify
    assert "assert '$CURRENT_RUNNER_NAME' == '$EXPECTED_DISCOVERY_RUNNER_NAME'" in requalify


def test_requalification_uses_fresh_source_root_and_never_cleans_shared_workspace() -> None:
    requalify = _section(_text(), "requalify-physical", "persist-proof")
    expected_source_root = '$HOME/.local/share/nexus/multipair-requalification-source/$GITHUB_RUN_ID'
    assert expected_source_root in requalify
    assert '"$HOME"/.local/share/nexus/multipair-requalification-source/*)' in requalify
    assert 'git -C "$source_root" init .' in requalify
    assert 'git clean -ffdx' not in requalify
    assert 'git reset --hard' not in requalify
    assert "multipair_requalification_fresh_source_checkout=PASS" in requalify


def test_discovery_v2_uses_safe_external_ephemeral_state_and_canonical_wheelhouse() -> None:
    text = _text()
    expected_root = '$HOME/.local/share/nexus/multipair-discovery-v2/$GITHUB_RUN_ID'
    assert text.count(expected_root) >= 2
    assert '"$HOME"/.local/share/nexus/multipair-discovery-v2/*)' in text
    assert "multipair_discovery_state_storage=physical_external_ephemeral_path" in text
    assert "multipair_discovery_state_recovered_from_external_path=PASS" in text
    assert "--output build/nexus-paper-runtime-wheelhouse.zip" in text
    assert "path: build/nexus-paper-runtime-wheelhouse.zip" in text
    assert 'cmp "$SOURCE_ROOT/requirements.lock" "$state_root/requirements.lock"' in text
    assert 'rm -rf "$state_root"' in text
    assert 'rm -rf "$source_root"' in text


def test_physical_python_bootstrap_uses_bundled_pip_for_install_and_check() -> None:
    text = _text()
    discover = _section(text, "discover-physical", "runtime-snapshot")
    requalify = _section(text, "requalify-physical", "persist-proof")
    assert 'bundled = Path(ensurepip.__file__).resolve().parent / "_bundled"' in discover
    assert 'PYTHONPATH="$pip_wheel" "$PYTHON_BIN" -m pip install' in discover
    assert "printf 'PYTHONPATH=%s:%s\\n' \"$pip_wheel\" \"$runtime_site\" >> \"$GITHUB_ENV\"" in discover
    assert "name: Verify isolated runtime dependency consistency" in discover
    assert 'bundled = Path(ensurepip.__file__).resolve().parent / "_bundled"' in requalify
    assert 'test -f "$pip_wheel"' in requalify
    assert "printf 'PYTHONPATH=%s:%s:%s\\n' \"$pip_wheel\" \"$state_root/runtime-site\" \"$source_root\" >> \"$GITHUB_ENV\"" in requalify
    assert "name: Verify recovered isolated runtime dependency consistency" in requalify


def test_discover_job_restores_and_independently_verifies_exact_archive_snapshot() -> None:
    discover = _section(_text(), "discover-physical", "runtime-snapshot")
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


def test_requalification_restores_fresh_digest_pinned_snapshot_and_never_calls_rest_directly() -> None:
    requalify = _section(_text(), "requalify-physical", "persist-proof")
    assert "needs: [discover-physical, runtime-snapshot]" in requalify
    assert "scripts/nexus_runtime_snapshot_artifact.py" in requalify
    assert '--expected-sha256 "$RUNTIME_SNAPSHOT_ARCHIVE_SHA256"' in requalify
    assert '--expected-snapshot-digest "$EXPECTED_RUNTIME_SNAPSHOT_DIGEST"' in requalify
    assert '--expected-as-of-ms "$EXPECTED_RUNTIME_SNAPSHOT_AS_OF_MS"' in requalify
    assert '--destination "$STATE_ROOT/runtime-snapshot"' in requalify
    assert "nexus_multipair_runtime_requalification_snapshot.py requalify" in requalify
    assert 'assert result["blocked_runtime_data_count"] == 0' in requalify
    assert 'assert result["status"] in {"NO_WORK", "EVALUATED"}' in requalify
    assert 'assert result["runtime_data_is_fresh_not_snapshot_reuse"] is True' in requalify
    assert 'assert result["runtime_snapshot_distinct_from_discovery"] is True' in requalify
    assert 'assert result["historical_discovery_snapshot_reused"] is False' in requalify
    assert "from nexus_multipair_runtime_requalification_snapshot import TRANSPORT_ORIGIN, verify_fresh_runtime_snapshot" in requalify
    assert 'assert result["runtime_data_transport"] == TRANSPORT_ORIGIN' in requalify
    assert 'assert result["candidate_creation_authority"] is False' in requalify
    assert 'assert result["paper_execution_started"] is False' in requalify
    assert 'assert result["automatic_strategy_promotion"] is False' in requalify
    assert 'assert result["live_trading_authority"] is False' in requalify
    assert 'assert result["private_credentials_used"] is False' in requalify
    assert 'assert result["deterministic_risk_final_authority"] is True' in requalify
    assert "from nexus_multipair_strategy_proposal_requalification import run" not in requalify


def test_persisted_proof_records_historical_and_fresh_runtime_evidence_without_authority_escalation() -> None:
    text = _text()
    assert '"symbols": list(SYMBOLS)' in text
    assert '"timeframes": list(TIMEFRAMES)' in text
    assert '"families": list(FAMILIES)' in text
    assert '"snapshot_transport": "digest_pinned_current_run_github_artifact"' in text
    assert '"snapshot_data_origin": snapshot["data_origin"]' in text
    assert '"snapshot_runtime_freshness_claimed": snapshot["runtime_freshness_claimed"]' in text
    assert '"snapshot_as_of_ms": discovery["snapshot_as_of_ms"]' in text
    assert '"runtime_snapshot_transport": requalification["runtime_data_transport"]' in text
    assert '"runtime_snapshot_digest": runtime_snapshot["snapshot_digest"]' in text
    assert '"runtime_snapshot_as_of_ms": runtime_snapshot["as_of_ms"]' in text
    assert '"runtime_snapshot_history_limit": runtime_snapshot["history_limit"]' in text
    assert '"runtime_snapshot_distinct_from_discovery": requalification["runtime_snapshot_distinct_from_discovery"]' in text
    assert '"historical_discovery_snapshot_reused": requalification["historical_discovery_snapshot_reused"]' in text
    assert '"runtime_snapshot_freshness_verified": True' in text
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
