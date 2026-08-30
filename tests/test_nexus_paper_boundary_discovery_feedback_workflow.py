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
    section = text.split("requalify-boundary-proposals:", 1)[1]
    assert "runs-on: nexus-bybit-network" in section
    assert "runner.environment" in section
    assert "runner.os" in section
    assert "self-hosted" in section
    assert "Linux" in section
    assert "nexus_strategy_proposal_runtime_requalification.py" in section
    assert "nexus_paper_boundary_discovery_feedback.py feedback" in section
    assert "Require exact Paper 4h boundary coverage" in section


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
