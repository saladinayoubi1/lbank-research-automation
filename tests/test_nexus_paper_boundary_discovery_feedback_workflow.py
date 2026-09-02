import json
from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_paper_boundary_discovery_feedback.yml")
RECOVERY = Path(".nexus/recovery/paper-boundary-feedback-v1.json")


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


def test_recovery_trigger_is_repository_bound_and_fail_closed() -> None:
    text = _text()
    assert "recovery_paper_run_id:" in text
    assert ".nexus/recovery/paper-boundary-feedback-v1.json" in text
    assert "Resolve and validate exact successful main Paper completion" in text
    assert 'value.get("name") != "NEXUS persistent Paper trading loop"' in text
    assert (
        'value.get("path") != ".github/workflows/nexus_persistent_paper_trading_loop.yml"'
        in text
    )
    assert 'value.get("head_branch") != "main"' in text
    assert 'value.get("event") not in {"push", "schedule", "workflow_dispatch"}' in text
    assert "recovery Paper run repository mismatch" in text
    assert "recovery Paper head repository mismatch" in text
    assert "Recovery manifest source SHA does not match the Paper run" in text
    assert "recovery_paper_state_artifact_binding=PASS" in text
    assert "recovery Paper state artifact digest mismatch" in text
    assert "recovery Paper state artifact run binding mismatch" in text
    assert "recovery Paper state artifact source binding mismatch" in text
    assert 'artifact_id="${PAPER_STATE_ARTIFACT_ID:-}"' in text
    assert 'sha256sum build/trigger-paper.zip' in text
    assert "workflow_run source SHA does not match its GitHub run metadata" in text
    assert "validated_paper_recovery_trigger=PASS" in text
    assert "steps.trigger.outputs.eligible == 'true'" in text

    recovery = json.loads(RECOVERY.read_text(encoding="utf-8"))
    assert recovery["schema"] == "nexus-paper-boundary-recovery/v1"
    assert recovery["paper_run_id"] == 33578362809
    assert recovery["expected_source_sha"] == (
        "662a0d325d6648f0d57c2b252645082f83c42737"
    )
    assert recovery["paper_state_artifact_id"] == 9827586931
    assert recovery["paper_state_artifact_sha256"] == (
        "b56106750a758ebc21b3414dddf15b436a753c32e9c6ad334e5ba2cfd3e35e9f"
    )
    assert "33578757046" in recovery["reason"]


def test_workflow_binds_discovery_to_triggering_paper_sha() -> None:
    text = _text()
    binding = "needs.gate-paper-boundary.outputs.trigger_source_sha"
    assert text.count(binding) >= 4
    assert "trigger_source_sha: ${{ steps.trigger.outputs.trigger_source_sha }}" in text
    assert "trigger_run_id: ${{ steps.trigger.outputs.trigger_run_id }}" in text
    assert '--source-sha "$TRIGGER_SOURCE_SHA"' in text
    assert "paper-boundary-context.json" in text
    assert "hour4_boundary_digest" in text
    assert "context[\"source_sha\"] == discovery[\"source_sha\"]" in text


def test_workflow_requalification_uses_physical_bybit_linux_plane() -> None:
    text = _text()
    section = text.split("requalify-boundary-proposals:", 1)[1].split(
        "persist-boundary-feedback:", 1
    )[0]
    assert "runs-on: nexus-bybit-network" in section
    assert "runner.environment" in section
    assert "runner.os" in section
    assert "self-hosted" in section
    assert "Linux" in section
    assert "Prepare exact repository and pre-provisioned Python 3.12 without JavaScript actions" in section
    assert "actions/checkout" not in section
    assert "actions/setup-python" not in section
    assert "actions/upload-artifact" not in section
    assert "requalification_wheelhouse_verification=PASS" in section
    assert "offline_wheelhouse_bootstrap=PASS" in section
    assert '--no-index' in section
    assert "nexus_strategy_proposal_runtime_requalification.py" in section
    assert "nexus_paper_boundary_discovery_feedback.py feedback" in section
    assert "Require exact Paper 4h boundary coverage" in section


def test_physical_feedback_is_bounded_and_persisted_by_hosted_job() -> None:
    text = _text()
    physical = text.split("requalify-boundary-proposals:", 1)[1].split(
        "persist-boundary-feedback:", 1
    )[0]
    hosted = text.split("persist-boundary-feedback:", 1)[1]

    assert "Package physical feedback for hosted persistence" in physical
    assert "compression=zipfile.ZIP_LZMA" in physical
    assert "feedback_archive_chunk_count" in physical
    assert 'feedback_b64_bytes" -gt 480000' in physical
    assert "chunk_size=60000" in physical
    assert "max_chunks=8" in physical
    for index in range(8):
        assert f"feedback_archive_chunk_{index}" in physical
        assert f"needs.requalify-boundary-proposals.outputs.feedback_archive_chunk_{index}" in hosted

    assert "runs-on: ubuntu-latest" in hosted
    assert "hosted_feedback_handoff_verification=PASS" in hosted
    assert "FEEDBACK_ARCHIVE_SHA256" in hosted
    assert "unsafe feedback handoff path" in hosted
    assert "nexus-paper-boundary-discovery-feedback-${{ github.run_id }}" in hosted


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
