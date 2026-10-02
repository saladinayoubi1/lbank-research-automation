from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_verified_perpetual_positioning.yml")


def test_positioning_workflow_is_read_only_research_evidence_only():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    assert "--start 2026-07-03T00:00:00Z" in text
    assert "--end-exclusive 2026-08-02T00:00:00Z" in text
    assert 'p["oi_value_field"] == "singleOpenInterest"' in text
    assert 'p["derivatives_execution_authority"] is False' in text
    assert 'p["automatic_strategy_promotion"] is False' in text
    assert 'p["live_trading_authority"] is False' in text
    assert 'p["credentials_used"] is False' in text
    assert "secrets." not in text
