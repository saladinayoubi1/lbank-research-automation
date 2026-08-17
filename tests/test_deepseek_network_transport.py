from __future__ import annotations

import pytest

import deepseek_provider as ds
from deepseek_network_transport import (
    DEEPSEEK_CHAT_URL,
    MAX_RESPONSE_BYTES,
    authorize_deepseek_json,
    post_authorized_json,
)
from network_egress import EgressDenied


PUBLIC_IP = "93.184.216.34"


def _authorized(body: bytes):
    from network_egress import NetworkEgressAuthorizer

    authorizer = NetworkEgressAuthorizer(resolver=lambda _host, _port: [PUBLIC_IP])
    return authorize_deepseek_json(body, authorizer=authorizer)


def test_deepseek_request_is_authorized_to_exact_host_path_and_ip():
    body = b'{"model":"bounded"}'
    authorizer, authorized = _authorized(body)
    assert authorized.url == DEEPSEEK_CHAT_URL
    assert authorized.host == "api.deepseek.com"
    assert authorized.port == 443
    assert authorized.path_and_query == "/chat/completions"
    assert authorized.resolved_ips == (PUBLIC_IP,)
    assert authorized.request_bytes == len(body)
    assert authorizer is not None


class _Response:
    def __init__(self, *, status=200, payload=b"{}", location=None):
        self.status = status
        self._payload = payload
        self._location = location

    def getheader(self, name):
        return self._location if name.lower() == "location" else None

    def read(self, amount):
        return self._payload[:amount]


class _Connection:
    response = _Response()
    seen = []

    def __init__(self, authorized, authorizer, *, timeout):
        self.authorized = authorized
        self.authorizer = authorizer
        self.timeout = timeout

    def request(self, method, path, *, body, headers):
        type(self).seen.append((method, path, body, dict(headers)))

    def getresponse(self):
        return type(self).response

    def close(self):
        pass


def test_transport_uses_only_pre_authorized_method_and_path():
    body = b'{"model":"bounded"}'
    authorizer, authorized = _authorized(body)
    _Connection.response = _Response(status=200, payload=b'{"ok":true}')
    _Connection.seen = []
    result = post_authorized_json(
        body=body,
        headers={"Authorization": "Bearer test", "Content-Type": "application/json"},
        authorized=authorized,
        authorizer=authorizer,
        timeout=2,
        connection_factory=_Connection,
    )
    assert result == b'{"ok":true}'
    assert _Connection.seen == [("POST", "/chat/completions", body, {"Authorization": "Bearer test", "Content-Type": "application/json"})]


def test_redirect_is_denied_without_following_location():
    body = b"{}"
    authorizer, authorized = _authorized(body)
    _Connection.response = _Response(status=302, payload=b"", location="https://attacker.invalid/")
    with pytest.raises(EgressDenied, match="redirect"):
        post_authorized_json(
            body=body,
            headers={"Content-Type": "application/json"},
            authorized=authorized,
            authorizer=authorizer,
            timeout=2,
            connection_factory=_Connection,
        )


def test_oversize_response_is_denied():
    body = b"{}"
    authorizer, authorized = _authorized(body)
    _Connection.response = _Response(status=200, payload=b"x" * (MAX_RESPONSE_BYTES + 1))
    with pytest.raises(EgressDenied, match="response byte limit"):
        post_authorized_json(
            body=body,
            headers={"Content-Type": "application/json"},
            authorized=authorized,
            authorizer=authorizer,
            timeout=2,
            connection_factory=_Connection,
        )


def test_body_must_match_authorized_byte_count():
    body = b"{}"
    authorizer, authorized = _authorized(body)
    with pytest.raises(EgressDenied, match="byte count"):
        post_authorized_json(
            body=b'{"changed":true}',
            headers={"Content-Type": "application/json"},
            authorized=authorized,
            authorizer=authorizer,
            timeout=2,
            connection_factory=_Connection,
        )


def test_provider_chat_uses_authorizer_and_pinned_transport_not_urlopen(monkeypatch, tmp_path):
    ledger = tmp_path / "usage.json"
    monkeypatch.setattr(ds, "CANONICAL_LEDGER", ledger)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")
    marker_authorizer = object()
    marker_request = object()
    seen = {}

    def authorize(body):
        seen["authorized_body"] = body
        return marker_authorizer, marker_request

    def post(**kwargs):
        seen["post"] = kwargs
        return (
            b'{"choices":[{"message":{"content":"NEXUS_DEEPSEEK_OK"}}],'
            b'"usage":{"prompt_tokens":1,"prompt_cache_hit_tokens":0,'
            b'"prompt_cache_miss_tokens":1,"completion_tokens":1}}'
        )

    def forbidden_urlopen(*_args, **_kwargs):
        raise AssertionError("urllib provider I/O must never be used")

    monkeypatch.setattr(ds, "authorize_deepseek_json", authorize)
    monkeypatch.setattr(ds, "post_authorized_json", post)
    monkeypatch.setattr(ds.request, "urlopen", forbidden_urlopen)

    result = ds.chat(
        [{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}],
        max_tokens=32,
        ledger_path=ledger,
    )

    assert result["content"] == "NEXUS_DEEPSEEK_OK"
    assert seen["post"]["authorized"] is marker_request
    assert seen["post"]["authorizer"] is marker_authorizer
    assert seen["post"]["body"] == seen["authorized_body"]
    assert ds.load_ledger(ledger)["inflight"] == {}
