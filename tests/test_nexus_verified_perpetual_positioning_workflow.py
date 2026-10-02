from pathlib import Path


WORKFLOW = Path(".github/workflows/nexus_verified_perpetual_positioning.yml")


def test_positioning_workflow_is_read_only_and_verifies_research_plane_proof():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request:" in text
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "permissions:\n  contents: read" in text
    assert "research/evidence/verified_perpetual_positioning_20260703_20260802.json" in text
    assert "verify_proof(proof)" in text
    assert "a59405c733ecc6cad5c9270155a22bab52173989cd62c9569cf37b06f844c6e6" in text
    assert 'proof["oi_rows"] == {"BTCUSDT": 720, "ETHUSDT": 720}' in text
    assert 'proof["funding_rows"] == {"BTCUSDT": 90, "ETHUSDT": 90}' in text
    assert 'proof["derivatives_execution_authority"] is False' in text
    assert 'proof["automatic_strategy_promotion"] is False' in text
    assert 'proof["live_trading_authority"] is False' in text
    assert "api.bybit" not in text
    assert "secrets." not in text
