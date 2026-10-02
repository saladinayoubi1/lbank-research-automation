from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_signed_flow_price_response_research.yml")


def test_a6_workflow_is_manual_research_only_and_uses_30_day_verified_inputs():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    assert "--start-date 2026-07-03" in text
    assert "--end-date 2026-08-01" in text
    assert "bybit_spot_archive_collector.py" in text
    assert "nexus_signed_flow_price_response_research.py" in text
    assert "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT" in text
    assert 'report["automatic_strategy_promotion"] is False' in text
    assert 'report["live_trading_authority"] is False' in text
    assert 'proof["raw_trade_rows_published"] is False' in text
    assert "secrets." not in text
