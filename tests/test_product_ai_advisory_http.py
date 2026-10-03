from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import product_ai_advisory as advisory
from product_offline_web_server import build_handler as build_offline_handler
from product_runtime import ProductRuntime
from product_web_server import build_handler as build_product_handler
from web_dashboard import GatewayConfig


def _request(port, method, path, payload=None, *, origin=None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    headers = {"Host": f"127.0.0.1:{port}"}
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    if origin:
        headers["Origin"] = origin
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    status, result = response.status, json.loads(response.read())
    conn.close()
    return status, result


@pytest.fixture(params=[build_product_handler, build_offline_handler], ids=["product", "desktop-offline"])
def gateway(request, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-fixture-only")
    monkeypatch.setattr(advisory.provider, "load_ledger", lambda: {
        "spent_usd": 0, "reserved_usd": 0, "inflight": {},
    })
    calls = []
    def provider_reply(messages, **kwargs):
        calls.append(messages)
        return {"content": "پژوهش هنوز نیاز به اعتبارسنجی مستقل دارد.",
                "model": advisory.provider.DEFAULT_MODEL, "cost_usd": 0.0001}
    monkeypatch.setattr(advisory.provider, "chat", provider_reply)
    data = tmp_path / "market"
    data.mkdir()
    runtime = ProductRuntime(tmp_path / "owner-state", opening_cash="500")
    server = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = server.server_address[1]
    server.RequestHandlerClass = request.param(data, runtime=runtime, config=GatewayConfig(
        mode="local", host="127.0.0.1", port=port,
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, runtime, calls
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _turn(message="research private-user-marker@example.test", turn="t1"):
    return {"session_id": "s1", "conversation_id": "c1", "turn_id": turn, "message": message}


def test_advisory_http_uses_real_gate_deduplicates_and_preserves_owner_journal(gateway):
    port, runtime, calls = gateway
    before = runtime.paper_events_path.read_bytes()
    status, readiness = _request(port, "GET", "/api/product/ai/provider")
    assert status == 200 and readiness["status"] == "ready_unverified"
    assert calls == []
    req = _turn()
    status, result = _request(port, "POST", "/api/product/ai/advisory", req)
    assert status == 200 and result["source"] == "external_advisory"
    assert result["decision"]["allowed"] is True
    assert result["state_mutation"] is False and result["live_trading_authority"] is False
    assert len(calls) == 1 and "private-user-marker" not in json.dumps(calls)
    assert _request(port, "POST", "/api/product/ai/advisory", req) == (200, result)
    assert len(calls) == 1
    assert runtime.paper_events_path.read_bytes() == before
    assert runtime.paper_snapshot()["account"]["cash"] == "500"
    assert _request(port, "GET", "/api/product/ai/provider")[1]["connection_verified"] is True
    internal_status, internal = _request(port, "POST", "/api/ai-room/message", _turn("show status", "t2"))
    assert internal_status == 200
    assert internal["ai_room"]["privacy"]["external_provider_called"] is False
    assert len(calls) == 1


@pytest.mark.parametrize("payload,query,origin,expected", [
    ({**_turn(), "decision": {"allowed": True}}, "", None, 400),
    (_turn("enable live trading in production"), "", None, 403),
    (_turn(), "?authority=4", None, 400),
    (_turn(), "", "https://untrusted.example", 403),
])
def test_advisory_http_rejects_authority_schema_query_and_foreign_origin(gateway, payload, query, origin, expected):
    port, runtime, calls = gateway
    before = runtime.paper_events_path.read_bytes()
    status, _ = _request(port, "POST", "/api/product/ai/advisory" + query, payload, origin=origin)
    assert status == expected
    assert calls == []
    assert runtime.paper_events_path.read_bytes() == before


def test_unavailable_external_model_does_not_block_original_room(gateway, monkeypatch):
    port, _, calls = gateway
    monkeypatch.delenv("DEEPSEEK_API_KEY")
    assert _request(port, "POST", "/api/product/ai/advisory", _turn())[0] == 503
    status, result = _request(port, "POST", "/api/ai-room/message", _turn("show status", "t2"))
    assert status == 200 and result["ai_room"]["decision"]["allowed"] is True
    assert calls == []


def test_chatgpt_context_is_gated_bounded_and_preserves_owner_state_without_provider_call(gateway):
    port, runtime, calls = gateway
    before = runtime.paper_events_path.read_bytes()
    status, context = _request(port, "POST", "/api/product/ai/chatgpt/context", _turn())
    assert status == 200 and context["decision"]["allowed"] is True
    assert context["state_mutation"] is False and context["live_trading_authority"] is False
    outbound = json.dumps(context["input"])
    assert "private-user-marker" not in outbound
    assert "500" not in outbound and "Independent Verifier" in outbound
    assert calls == [] and runtime.paper_events_path.read_bytes() == before
    for payload in (_turn("enable live trading in production"), {**_turn(), "decision": {"allowed": True}}):
        assert _request(port, "POST", "/api/product/ai/chatgpt/context", payload)[0] in (400, 403)
    assert _request(port, "POST", "/api/product/ai/chatgpt/context", _turn(), origin="https://evil.example")[0] == 403
    assert _request(port, "POST", "/api/product/ai/chatgpt/context?authority=4", _turn())[0] == 400
    assert calls == [] and runtime.paper_events_path.read_bytes() == before


def test_chatgpt_reply_filter_redacts_pii_and_rejects_credentials_and_untrusted_fields(gateway):
    port, runtime, calls = gateway
    before = runtime.paper_events_path.read_bytes()
    route = "/api/product/ai/chatgpt/sanitize"
    status, result = _request(port, "POST", route, {"reply": "پاسخ contact@example.test"})
    assert status == 200 and "contact@example.test" not in result["reply"]
    assert "[REDACTED_EMAIL]" in result["reply"]
    assert _request(port, "POST", route, {"reply": "api_key=private-fixture-token"})[0] == 403
    assert _request(port, "POST", route, {"reply": "safe", "execute": True})[0] == 400
    assert _request(port, "POST", route, {"reply": "x" * 12001})[0] == 400
    assert _request(port, "POST", route, {"reply": "safe"}, origin="https://evil.example")[0] == 403
    assert calls == [] and runtime.paper_events_path.read_bytes() == before


def test_council_projection_is_canonical_configuration_without_fabricated_votes(gateway):
    port, _, calls = gateway
    status, roadmap = _request(port, "GET", "/api/product/ai/roadmap")
    assert status == 200 and roadmap["council"]["status"] == "configured"
    c = roadmap["council"]
    assert c["quorum"] == 2 and c["votes"] == [] and c["decision"] == "not_evaluated"
    assert {r["id"]: r["veto"] for r in c["roles"]} == {"stability": True, "security": True, "delivery": False}
    assert roadmap["model_advice_is_council_vote"] is False
    assert roadmap["model_advice_is_independent_qa"] is False
    assert roadmap["live_trading_authority"] is False and calls == []
