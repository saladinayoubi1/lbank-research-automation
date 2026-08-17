from pathlib import Path

import pytest

import deepseek_egress as egress
import deepseek_provider as ds


def _configure_no_network(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "usage.json"
    monkeypatch.setattr(ds, "CANONICAL_LEDGER", path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")

    def network_must_not_run(*_args, **_kwargs):
        raise AssertionError("provider network must not be reached for denied egress")

    monkeypatch.setattr(ds, "authorize_deepseek_json", network_must_not_run)
    monkeypatch.setattr(ds, "post_authorized_json", network_must_not_run)
    return path


def test_health_smoke_is_explicitly_classified():
    classification, messages = egress.prepare_egress_messages(
        [{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}]
    )
    assert classification == "health_smoke"
    assert messages == [{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}]


def test_research_payload_redacts_incidental_identity_data():
    content = (
        "You are an independent quantitative-research reviewer for NEXUS.\n"
        "Review repository evidence owned by analyst@example.com under /home/alice/work only."
    )
    classification, messages = egress.prepare_egress_messages([{"role": "user", "content": content}])
    assert classification == "research_advisory"
    assert "analyst@example.com" not in messages[0]["content"]
    assert "/home/alice" not in messages[0]["content"]
    assert "[REDACTED_EMAIL]" in messages[0]["content"]
    assert "[REDACTED_USER_PATH]" in messages[0]["content"]


@pytest.mark.parametrize(
    "content",
    [
        "Authorization: Bearer super-secret-token-value",
        "You are an independent quantitative-research reviewer for NEXUS.\napi_key=abcdefghijklmnop",
        "You are an independent quantitative-research reviewer for NEXUS.\nprivate account number: 1234567890123456",
        "You are an independent quantitative-research reviewer for NEXUS.\nRAW_CHAT_TRANSCRIPT: private message",
    ],
)
def test_sensitive_or_unclassified_payload_is_denied(content):
    with pytest.raises(egress.EgressDenied):
        egress.prepare_egress_messages([{"role": "user", "content": content}])


def test_unallowlisted_message_fields_are_denied():
    with pytest.raises(egress.EgressDenied, match="fields"):
        egress.prepare_egress_messages(
            [{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK", "private_metadata": "x"}]
        )


def test_provider_denies_sensitive_payload_before_budget_or_network(monkeypatch, tmp_path):
    path = _configure_no_network(monkeypatch, tmp_path)

    with pytest.raises(ds.DeepSeekError, match="egress"):
        ds.chat(
            [{"role": "user", "content": "Authorization: Bearer super-secret-token-value"}],
            ledger_path=path,
            max_tokens=32,
        )

    assert not path.exists(), "denied egress must not consume or reserve budget"
