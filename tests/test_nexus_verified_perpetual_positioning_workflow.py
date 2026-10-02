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
    assert "Build fresh public positioning proof" in text
    assert "python nexus_verified_perpetual_positioning.py" in text
    assert "--output-root build/perpetual-positioning-fresh" in text
    assert "Compare fresh proof with committed evidence" in text
    assert '"dataset_semantic_sha256"' in text
    assert '"oi_value_field"' in text
    assert '"oi_methodology"' in text
    assert "fresh_positioning_evidence=PASS" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text
    assert "nexus-verified-perpetual-positioning-${{ github.sha }}" in text
    assert "api.bybit" not in text
    assert "secrets." not in text
