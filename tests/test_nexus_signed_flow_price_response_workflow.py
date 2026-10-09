from pathlib import Path

WORKFLOW = Path(".github/workflows/nexus_signed_flow_price_response_research.yml")


def test_a6_workflow_preserves_historical_research_and_adds_only_preregistered_qa():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "push:" in text
    assert "branches:\n      - main" in text
    assert 'default: historical' in text
    assert 'options: [historical, live-side, future]' in text
    assert 'cron: "15 4 10 10 *"' in text
    assert 'cron: "15 4 9 11 *"' in text
    assert text.count("cron:") == 2
    assert "datetime.now(timezone.utc).year == 2026" in text
    assert "if mode not in {'historical', 'live-side', 'future'}:" in text
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
    assert "ref: d72c92f315abd514fd7210388ce211258a670799" in text
    assert "scripts/nexus_a6_preregistered_validation.py" in text
    assert "--model-root frozen-model" in text
    assert text.count("steps.window.outputs.mode == 'historical'") == 4
