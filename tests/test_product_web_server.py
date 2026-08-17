from __future__ import annotations

import io
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from product_runtime import ProductRuntime
from product_web_server import PRODUCT_UI_ROOT, build_handler
from web_dashboard import GatewayConfig


def _request(port: int, method: str, path: str, payload: dict | None = None):
    conn = HTTPConnection("127.0.0.1", port, timeout=5)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
        headers["Content-Length"] = str(len(body))
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    raw = response.read()
    content_type = response.getheader("Content-Type") or ""
    conn.close()
    return response.status, content_type, raw


@pytest.fixture
def product_server(tmp_path: Path):
    data_root = tmp_path / "data" / "market"
    data_root.mkdir(parents=True)
    runtime = ProductRuntime(tmp_path / "state")
    server = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(
        data_root,
        config=GatewayConfig(mode="local", host="127.0.0.1", port=1),
        ui_root=PRODUCT_UI_ROOT,
        runtime=runtime,
    ))
    # Handler allowlists the configured port, so rebuild using the actual port.
    port = server.server_address[1]
    server.server_close()
    server = ThreadingHTTPServer(("127.0.0.1", port), build_handler(
        data_root,
        config=GatewayConfig(mode="local", host="127.0.0.1", port=port),
        ui_root=PRODUCT_UI_ROOT,
        runtime=runtime,
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, runtime
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_product_ui_contains_real_roadmap_surfaces(product_server) -> None:
    port, _ = product_server
    status, content_type, raw = _request(port, "GET", "/")
    assert status == 200
    assert "text/html" in content_type
    text = raw.decode("utf-8")
    for token in (
        "ترید دمو", "اتاق هوش مصنوعی", "Strategy Lab", "Research Lab",
        "تصمیم و ریسک", "عامل‌ها و صف", "رویداد و بازپخش", "ترید اصلی",
        "OWNER-CONTROLLED FUTURE STAGE",
    ):
        assert token in text


def test_product_overview_reports_paper_active_and_live_locked(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/api/product/overview")
    assert status == 200
    payload = json.loads(raw)
    assert payload["paper"]["active"] is True
    assert payload["paper"]["paper_only"] is True
    assert payload["live"]["status"] == "locked_owner_controlled"
    assert payload["live"]["orders_allowed"] is False
    assert payload["capabilities"]["paper_execution"] == "active"
    assert payload["capabilities"]["ai_room"] == "policy_gated"


def test_product_paper_order_mutates_only_demo_state(product_server) -> None:
    port, runtime = product_server
    order = {
        "operation": "open",
        "symbol": "BTCUSDT",
        "timeframe": "minute15",
        "side": "long",
        "quantity": "0.001",
        "reference_price": "60000",
        "stop_price": "59000",
        "target_price": "62000",
    }
    status, _, raw = _request(port, "POST", "/api/product/paper/order", order)
    assert status == 200
    payload = json.loads(raw)
    assert payload["accepted"] is True
    assert payload["paper_only"] is True
    assert runtime.paper_snapshot()["account"]["positions"][0]["symbol"] == "BTCUSDT"
    live_status, _, live_raw = _request(port, "GET", "/api/product/live")
    assert live_status == 200
    live = json.loads(live_raw)
    assert live["enabled"] is False
    assert live["exchange_credentials_configured"] is False


def test_product_rejects_unknown_write_routes(product_server) -> None:
    port, _ = product_server
    status, _, _ = _request(port, "POST", "/api/product/live/order", {"symbol": "BTCUSDT"})
    assert status == 405


def test_product_strategies_are_real_factory_families(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/api/product/strategies")
    assert status == 200
    payload = json.loads(raw)
    ids = {row["id"] for row in payload["families"]}
    assert ids == {"momentum", "trend_breakout", "mean_reversion"}
    assert all(row["live_execution_allowed"] is False for row in payload["families"])


def test_product_static_script_is_same_origin_only(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/ui/product.js")
    assert status == 200
    script = raw.decode("utf-8")
    assert "https://" not in script
    assert "/api/product/paper/order" in script
    assert "/api/ai-room/message" in script
    assert "withdraw" not in script.casefold()
