from pathlib import Path

WORKFLOW = Path(".github/workflows/bybit_derivatives_validation_v1.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_derivatives_validation_does_not_pin_expiring_artifact_id():
    text = _text()
    assert "8867026863" not in text
    assert "bybit-full-history-final-rehydrated-" in text
    assert 'item.get("expired") is False' in text
    assert 'item["workflow_run"].get("head_branch") == "main"' in text
    assert "no unexpired main full-history rehydration artifact is available" in text


def test_derivatives_validation_rechecks_legacy_digest_and_delivery_contract():
    text = _text()
    assert "EXPECTED_SHA256" in text
    assert "historical_digest_match" in text
    assert "completed_units" in text
    assert "source_archives" in text
    assert "paper_replay_only" in text
    assert "live_trading_authority" in text
    assert "private_credentials_used" in text
