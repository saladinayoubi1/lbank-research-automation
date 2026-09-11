from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_strategy_proposal_runtime_requalification.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_contract_tests_active_workflow_while_runtime_keeps_trigger_lineage() -> None:
    text = _text()

    assert "jobs:\n  contract-test:" in text
    assert "ref: ${{ github.sha }}" in text
    assert "TRIGGER_SOURCE_SHA: ${{ github.event.workflow_run.head_sha }}" in text
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in text


def test_exact_exhaustion_reuse_is_verified_before_no_work() -> None:
    text = _text()

    assert "id: trigger" in text
    assert "reused-exhaustion-certificate.json" in text
    assert "search-neighborhood.json" in text
    assert "from nexus_multitimeframe_search_exhaustion import (" in text
    assert "build_neighborhood," in text
    assert "certificate_is_reusable," in text
    assert "verify_certificate," in text
    assert "verify_neighborhood," in text
    assert "artifact_neighborhood == current_neighborhood" in text
    assert "certificate_is_reusable(current_neighborhood, certificate)" in text
    assert 'certificate["source_sha"] == trigger_source_sha' in text
    assert 'certificate["base_research_proposal_count"] == 0' in text
    assert 'certificate["refined_research_proposal_count"] == 0' in text
    assert 'certificate["locked_holdout_used_for_refinement"] is False' in text
    assert 'certificate["selection_basis"] == "training_only"' in text
    assert (
        'dataset_semantic_sha256="2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422"'
        in text
    )


def test_no_work_mode_cannot_run_runtime_requalification() -> None:
    text = _text()

    assert 'echo "mode=proposal_queue" >> "$GITHUB_OUTPUT"' in text
    assert 'echo "mode=exhausted_reuse" >> "$GITHUB_OUTPUT"' in text
    assert (
        "- name: Requalify proposals on canonical public runtime data\n"
        "        if: steps.trigger.outputs.mode == 'proposal_queue'"
        in text
    )
    assert (
        "- name: Verify fail-closed authority boundary\n"
        "        if: steps.trigger.outputs.mode == 'proposal_queue'"
        in text
    )
    assert (
        "- name: Verify exact exhausted no-work authority boundary\n"
        "        if: steps.trigger.outputs.mode == 'exhausted_reuse'"
        in text
    )


def test_verified_no_work_evidence_preserves_research_paper_authority() -> None:
    text = _text()

    assert '"schema_version": "nexus.strategy-proposal-runtime-requalification-no-work.v1"' in text
    assert '"status": "NO_WORK"' in text
    assert '"reason": "exact_exhausted_neighborhood_reused"' in text
    assert '"proposal_count": 0' in text
    assert '"qualification_claimed": False' in text
    assert '"research_only": True' in text
    assert '"paper_only": True' in text
    assert '"paper_execution_started": False' in text
    assert '"live_trading_authority": False' in text
    assert '"private_credentials_used": False' in text
    assert '"automatic_strategy_promotion": False' in text
    assert "assert claimed == actual" in text
    assert "if-no-files-found: error" in text


def test_contract_job_covers_exhaustion_and_workflow_regression() -> None:
    text = _text()

    assert "tests/test_nexus_strategy_proposal_runtime_requalification_workflow.py" in text
    assert "tests/test_nexus_multitimeframe_search_exhaustion.py" in text
