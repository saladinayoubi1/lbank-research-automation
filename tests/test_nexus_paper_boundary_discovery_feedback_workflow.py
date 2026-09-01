from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_paper_boundary_discovery_feedback.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_is_health_driven_from_exact_paper_completion() -> None:
    text = _text()
    assert "workflow_run:" in text
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text
    assert "actions/runs/$TRIGGER_RUN_ID/artifacts" in text
    assert "nexus-persistent-paper-trading-state" in text
    assert "nexus_strategy_discovery_health_trigger.py" in text
    assert "steps.health.outputs.should_dispatch == 'true'" in text


def test_workflow_binds_discovery_to_triggering_paper_sha() -> None:
    text = _text()
    binding = "github.event.workflow_run.head_sha"
    assert text.count(binding) >= 5
    assert '--source-sha "$TRIGGER_SOURCE_SHA"' in text
    assert "paper-boundary-context.json" in text
    assert "hour4_boundary_digest" in text
    assert "context[\"source_sha\"] == discovery[\"source_sha\"]" in text


def test_workflow_requalification_uses_physical_bybit_linux_plane() -> None:
    text = _text()
    section = text.split("requalify-boundary-proposals:", 1)[1].split(
        "persist-requalification-evidence:", 1
    )[0]
    assert "runs-on: nexus-bybit-network" in section
    assert "runner.environment" in section
    assert "runner.os" in section
    assert "self-hosted" in section
    assert "Linux" in section
    assert "nexus_strategy_proposal_runtime_requalification.py" in section
    assert "nexus_paper_boundary_discovery_feedback.py feedback" in section
    assert "Require exact Paper 4h boundary coverage" in section


def test_physical_requalification_avoids_javascript_actions_and_broken_toolcache_pip() -> None:
    text = _text()
    section = text.split("  requalify-boundary-proposals:", 1)[1].split(
        "  persist-requalification-evidence:", 1
    )[0]
    assert "uses:" not in section
    assert "actions/checkout@" not in section
    assert "actions/setup-python@" not in section
    assert "actions/upload-artifact@" not in section
    assert "ACTIONS_ALLOW_USE_UNSECURE_NODE_VERSION" not in section
    assert "Prepare exact repository and pre-provisioned Python 3.12 without JavaScript actions" in section
    assert 'known_python="/opt/nexus-bybit-runner/_work/_tool/Python/3.12.14/x64/bin/python"' in section
    assert 'git fetch --no-tags --prune --depth=1 origin "$TRIGGER_SOURCE_SHA"' in section
    assert 'test "$(git rev-parse HEAD)" = "$TRIGGER_SOURCE_SHA"' in section
    assert "scripts/nexus_runtime_wheelhouse.py restore-current-run" in section
    assert "--no-index" in section
    assert "--find-links" in section
    assert "--target" in section
    assert "offline_requalification_wheelhouse_bootstrap=PASS" in section
    assert '"$PYTHON_BIN" -m pip check' in section


def test_requalification_evidence_is_bounded_and_persisted_on_hosted_runner() -> None:
    text = _text()
    physical = text.split("  requalify-boundary-proposals:", 1)[1].split(
        "  persist-requalification-evidence:", 1
    )[0]
    hosted = text.split("  persist-requalification-evidence:", 1)[1]
    assert "Package physical requalification evidence for hosted persistence" in physical
    assert "evidence_archive_chunk_count" in physical
    assert "evidence_archive_b64_len" in physical
    assert "evidence_archive_sha256" in physical
    assert "chunk_size=60000" in physical
    assert "max_chunks=8" in physical
    assert 'evidence_b64_bytes" -gt 480000' in physical
    for index in range(8):
        assert f"evidence_archive_chunk_{index}" in physical
        assert f"EVIDENCE_ARCHIVE_CHUNK_{index}" in hosted
    assert "runs-on: ubuntu-latest" in hosted
    assert "Rehydrate and verify physical requalification evidence" in hosted
    assert "hosted_requalification_evidence_handoff_verification=PASS" in hosted
    assert "Unexpected trailing requalification evidence handoff chunk." in hosted
    assert "Requalification evidence handoff length mismatch." in hosted
    assert "unsafe requalification evidence path" in hosted
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in hosted
    assert "nexus-paper-boundary-discovery-feedback-${{ github.run_id }}" in hosted


def test_requalification_wheelhouse_is_hosted_digest_pinned_and_offline_on_physical() -> None:
    text = _text()
    hosted = text.split("  requalification-wheelhouse:", 1)[1].split(
        "  requalify-boundary-proposals:", 1
    )[0]
    physical = text.split("  requalify-boundary-proposals:", 1)[1].split(
        "  persist-requalification-evidence:", 1
    )[0]
    assert "runs-on: ubuntu-latest" in hosted
    assert "python -m pip download" in hosted
    assert "--only-binary=:all:" in hosted
    assert "scripts/nexus_runtime_wheelhouse.py pack" in hosted
    assert "archive_sha256" in hosted
    assert "hosted_requalification_wheelhouse_smoke=PASS" in hosted
    assert "WHEELHOUSE_ARCHIVE_SHA256: ${{ needs.requalification-wheelhouse.outputs.archive_sha256 }}" in physical
    assert '--expected-sha256 "$WHEELHOUSE_ARCHIVE_SHA256"' in physical
    assert '--run-id "$GITHUB_RUN_ID"' in physical


def test_workflow_uses_only_approved_immutable_discovery_archive() -> None:
    text = _text()
    assert 'IMMUTABLE_ARCHIVE_ARTIFACT_ID: "8867026863"' in text
    assert (
        'EXPECTED_ARCHIVE_SHA256: "5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668"'
        in text
    )
    assert "sha256sum" in text
    assert "BYBIT_full_history_2022-12-01_to_2026-07-31.zip" in text
    assert "testnet" not in text.lower()
    assert "proxy" not in text.lower()
    assert "vpn" not in text.lower()


def test_workflow_preserves_fail_closed_authority_boundary() -> None:
    text = _text()
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "actions: read" in permissions
    assert "contents: write" not in permissions
    assert "actions: write" not in permissions
    assert "id-token: write" not in permissions
    assert "secrets." not in text
    assert "live_trading_authority" in text
    assert "automatic_strategy_promotion" in text
    assert "if: always()" in text
