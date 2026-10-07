from pathlib import Path

WORKFLOW = Path(".github/workflows/bybit_derivatives_validation_v1.yml")


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_derivatives_validation_does_not_pin_expiring_artifact_id():
    text = _text()
    assert "8867026863" not in text
    assert "bybit-full-history-final-rehydrated-" in text
    assert 'item.get("expired") is False' in text
    assert 'run.get("head_branch") == "main"' in text
    assert "gh api --paginate --slurp" not in text
    assert "scripts/select_nexus_bybit_replay_artifact.py" in text
    assert "--max-candidates 3" in text


def test_derivatives_validation_rechecks_canonical_content_and_delivery_contract():
    text = _text()
    assert "EXPECTED_SEMANTIC_SHA256" in text
    assert "assert expected == ARCHIVE_SHA256" in text
    assert "expected_semantic_sha256=expected" in text
    assert "manifest = build_manifest" in text
    assert 'assert manifest["semantic_dataset_sha256"] == expected' in text
    assert 'run["path"] == ".github/workflows/bybit_full_history_backfill.yml"' in text
    assert 'run["status"] == "completed" and run["conclusion"] == "success"' in text
    assert "paper_replay_only" in text
    assert "live_trading_authority" in text
    assert "private_credentials_used" in text
    assert "assert report['frozen_parameters_changed'] is False" in text
    assert "assert report['summary']['all_profiles_pass'] is True" in text
