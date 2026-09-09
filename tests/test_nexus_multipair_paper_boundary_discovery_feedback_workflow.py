from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_multipair_paper_boundary_discovery_feedback.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_listens_to_both_exact_evidence_producers() -> None:
    text = _text()
    assert '"NEXUS persistent Paper trading loop"' in text
    assert '"NEXUS Multi-Pair Discovery v2 physical proof"' in text
    assert "types: [completed]" in text
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert "github.event.workflow_run.head_branch == 'main'" in text


def test_workflow_requires_exact_sha_successful_counterparts() -> None:
    text = _text()
    assert "status=success&head_sha=$source_sha" in text
    assert 'row.get("head_sha") == source_sha' in text
    assert 'row.get("head_branch") == "main"' in text
    assert 'row.get("conclusion") == "success"' in text
    assert "exact_sha_feedback_pair=NOT_READY" in text
    assert "exact_sha_feedback_pair=PASS" in text


def test_workflow_uses_exact_paper_and_v2_proof_artifacts() -> None:
    text = _text()
    assert "nexus-persistent-paper-trading-state" in text
    assert "nexus-multipair-discovery-v2-proof-$SOURCE_SHA" in text
    assert "artifact {name} run binding mismatch" in text
    assert "sha256sum build/multipair-feedback/paper.zip" in text
    assert "sha256sum build/multipair-feedback/proof.zip" in text
    assert "nexus-multipair-paper-boundary-feedback-${{ steps.pair.outputs.source_sha }}" in text


def test_workflow_does_not_reexecute_discovery_or_market_data_acquisition() -> None:
    text = _text()
    assert "nexus_multitimeframe_verified_archive_discovery.py" not in text
    assert "nexus_multipair_runtime_requalification_snapshot.py acquire" not in text
    assert "nexus_multipair_runtime_requalification_snapshot.py requalify" not in text
    assert "IMMUTABLE_ARCHIVE_ARTIFACT_ID" not in text
    assert "8867026863" not in text
    assert "bybit_public_klines.py" not in text


def test_workflow_preserves_read_only_repository_and_actions_authority() -> None:
    text = _text()
    assert "permissions:\n  contents: read\n  actions: read" in text
    assert "secrets." not in text
    assert "private_credentials_used" in text
    assert "real_exchange_orders" in text
    assert "automatic_strategy_promotion" in text
    assert "issue_984_state_artifact_touched" in text
    assert "candidate_state_created" in text
    assert "paper_execution_started" in text


def test_workflow_only_links_natural_eligible_twelve_cell_boundary() -> None:
    text = _text()
    assert 'value.get("expected_cell_count") == 12' in text
    assert 'value.get("fresh_cell_count") == 12' in text
    assert 'value.get("expected_lane_count") == 36' in text
    assert 'value.get("regime_status") == "VERIFIED"' in text
    assert 'value.get("strategy_research_required") is True' in text
    assert 'value.get("strategy_discovery_health_trigger_requested") is True' in text
    assert "NO_OP_NOT_ELIGIBLE" in text
