from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus_multitimeframe_strategy_discovery.yml"


def test_workflow_reuses_only_exact_exhaustion_certificate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "EXHAUSTION_ARTIFACT: nexus-multitimeframe-search-exhaustion" in text
    assert "nexus_multitimeframe_search_exhaustion.py fingerprint" in text
    assert "nexus_multitimeframe_search_exhaustion.py check" in text
    assert "policy=exact_static_neighborhood_only" in text
    assert "steps.exhaustion.outputs.reuse != 'true'" in text
    assert "steps.exhaustion.outputs.reuse == 'true'" in text


def test_workflow_certifies_only_after_base_and_refinement_evidence() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Determine exact search exhaustion" in text
    assert "int(base[\"research_proposal_count\"]) == 0" in text
    assert "plan[\"should_refine\"] is True" in text
    assert "refined_count == 0" in text
    assert "nexus_multitimeframe_search_exhaustion.py certify" in text
    assert "Publish reusable exact exhaustion certificate" in text


def test_workflow_keeps_research_authority_frozen_on_reuse() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Verify reused exhaustion remains Research/Paper-only" in text
    assert 'assert certificate["locked_holdout_used_for_refinement"] is False' in text
    assert 'assert certificate["automatic_strategy_promotion"] is False' in text
    assert 'assert certificate["live_trading_authority"] is False' in text
    assert "cancel-in-progress: true" in text
