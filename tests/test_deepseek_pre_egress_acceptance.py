from pathlib import Path

import pytest

import deepseek_provider as ds


def _configure_no_network(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "usage.json"
    monkeypatch.setattr(ds, "CANONICAL_LEDGER", path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")

    def network_must_not_run(*_args, **_kwargs):
        raise AssertionError("provider network must not be reached for denied egress")

    monkeypatch.setattr(ds.request, "urlopen", network_must_not_run)
    return path


def test_authorization_bearer_payload_is_denied_before_network(monkeypatch, tmp_path):
    path = _configure_no_network(monkeypatch, tmp_path)

    with pytest.raises(ds.DeepSeekError, match="egress|payload|sensitive"):
        ds.chat(
            [{"role": "user", "content": "Authorization: Bearer super-secret-token-value"}],
            ledger_path=path,
            max_tokens=32,
        )

    assert not path.exists(), "denied egress must not consume or reserve budget"


def test_private_account_payload_is_denied_before_network(monkeypatch, tmp_path):
    path = _configure_no_network(monkeypatch, tmp_path)

    with pytest.raises(ds.DeepSeekError, match="egress|payload|sensitive"):
        ds.chat(
            [{"role": "user", "content": "private account number: 1234567890123456"}],
            ledger_path=path,
            max_tokens=32,
        )

    assert not path.exists(), "denied egress must not consume or reserve budget"


def test_unallowlisted_message_fields_are_denied_before_network(monkeypatch, tmp_path):
    path = _configure_no_network(monkeypatch, tmp_path)

    with pytest.raises(ds.DeepSeekError, match="egress|payload|allowlist"):
        ds.chat(
            [{"role": "user", "content": "bounded research", "private_metadata": "do-not-send"}],
            ledger_path=path,
            max_tokens=32,
        )

    assert not path.exists(), "denied egress must not consume or reserve budget"
