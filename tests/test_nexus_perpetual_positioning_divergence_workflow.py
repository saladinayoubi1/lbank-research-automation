from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_perpetual_positioning_divergence_research.yml")


def test_a9_workflow_is_read_only_research_and_uses_exact_30_day_inputs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "branches:\n      - main" in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    assert "--start-date 2026-07-03" in text
    assert "--end-date 2026-08-01" in text
    assert "nexus_perpetual_positioning_divergence_research.py" in text
    assert "bybit_spot_archive_collector.py" in text
    assert 'report["derivative_execution"] is False' in text
    assert 'report["automatic_strategy_promotion"] is False' in text
    assert 'report["live_trading_authority"] is False' in text
    assert "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT" in text
    assert "secrets." not in text
