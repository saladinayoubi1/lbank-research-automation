from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from product_runtime import ProductRuntime
from product_web_server import PRODUCT_UI_ROOT, _mission_snapshot, build_handler
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
    probe = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(
        data_root, config=GatewayConfig(mode="local", host="127.0.0.1", port=1),
        ui_root=PRODUCT_UI_ROOT, runtime=runtime,
    ))
    port = probe.server_address[1]
    probe.server_close()
    server = ThreadingHTTPServer(("127.0.0.1", port), build_handler(
        data_root, config=GatewayConfig(mode="local", host="127.0.0.1", port=port),
        ui_root=PRODUCT_UI_ROOT, runtime=runtime,
    ))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, runtime
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)


def test_product_ui_contains_complete_current_scope_surfaces(product_server) -> None:
    port, _ = product_server
    status, content_type, raw = _request(port, "GET", "/")
    assert status == 200 and "text/html" in content_type
    text = raw.decode("utf-8")
    for token in (
        "مرکز فرمان", "داده و بازار", "بک‌تست و پژوهش", "ترید دمو",
        "ریسک و پرتفوی", "اتاق هوش مصنوعی", "Strategy Lab", "عامل‌ها و صف",
        "ممیزی و بازیابی", "ترید اصلی", "OWNER-CONTROLLED FUTURE STAGE",
    ):
        assert token in text
    assert "/ui/product-extra.css" in text

    status, content_type, css = _request(port, "GET", "/ui/product-extra.css")
    assert status == 200 and "text/css" in content_type
    assert b"research-layout" in css


def test_product_overview_reports_canonical_backend_and_live_locked(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/api/product/overview")
    assert status == 200
    payload = json.loads(raw)
    assert payload["delivery"] == "canonical-python-sidecar"
    assert payload["paper"]["active"] is True
    assert payload["paper"]["paper_only"] is True
    assert payload["live"]["status"] == "locked_owner_controlled"
    assert payload["live"]["orders_allowed"] is False
    assert payload["mission_control"]["status"] == "idle"
    assert payload["mission_control"]["queue"]["counts"] == {"READY": 0, "RUNNING": 0, "FAILED": 0, "BLOCKED": 0}
    assert payload["mission_control"]["agents"] == []
    assert payload["capabilities"]["paper_execution"] == "active"
    assert payload["capabilities"]["research_backtest_studio"] == "active"
    assert payload["capabilities"]["automated_paper_pipeline"] == "qualification_and_risk_gated"
    assert payload["capabilities"]["ai_room"] == "policy_gated"
    assert payload["capabilities"]["mission_control"] == "idle"
    assert payload["capabilities"]["reports"] == "json_csv"


def test_clean_install_mission_control_is_truthful_idle_but_corrupt_state_fails_closed(tmp_path: Path) -> None:
    data_root = tmp_path / "data" / "market"
    data_root.mkdir(parents=True)
    clean = _mission_snapshot(data_root)
    assert clean["status"] == "idle"
    assert clean["projection"] == "clean_install_idle"
    assert clean["mission"]["status"] == "idle"
    assert clean["queue"]["counts"] == {"READY": 0, "RUNNING": 0, "FAILED": 0, "BLOCKED": 0}
    assert clean["agents"] == []
    assert clean["runners"] == []
    assert clean["providers"] == {}
    assert clean["local_node"]["registered"] is False
    assert clean["paper"]["live_trading_authority"] is False

    report = data_root.parent / "mission_control" / "_mission_control.json"
    report.parent.mkdir(parents=True)
    report.write_text("{}", encoding="utf-8")
    corrupt = _mission_snapshot(data_root)
    assert corrupt["status"] == "unavailable"
    assert "incompatible Mission Control report contract" in corrupt["reason"]
    assert report.read_text(encoding="utf-8") == "{}"


def test_product_paper_controls_and_order_mutate_only_demo_state(product_server) -> None:
    port, runtime = product_server
    status, _, raw = _request(port, "POST", "/api/product/session", {"open": False})
    assert status == 200 and json.loads(raw)["account"]["session_open"] is False
    status, _, raw = _request(port, "POST", "/api/product/session", {"open": True})
    assert status == 200 and json.loads(raw)["account"]["session_open"] is True

    order = {
        "operation": "open", "symbol": "BTCUSDT", "timeframe": "minute15",
        "side": "long", "quantity": "0.001", "reference_price": "60000",
        "stop_price": "59000", "target_price": "62000",
    }
    status, _, raw = _request(port, "POST", "/api/product/paper/order", order)
    assert status == 200
    payload = json.loads(raw)
    assert payload["accepted"] is True and payload["paper_only"] is True
    assert runtime.paper_snapshot()["account"]["positions"][0]["symbol"] == "BTCUSDT"

    status, _, raw = _request(port, "POST", "/api/product/kill-switch", {"enabled": True, "reason_code": "test_stop"})
    assert status == 200 and json.loads(raw)["account"]["kill_switch_enabled"] is True
    status, _, raw = _request(port, "POST", "/api/product/kill-switch", {"enabled": False, "reason_code": "test_resume"})
    assert status == 200 and json.loads(raw)["account"]["kill_switch_enabled"] is False

    live_status, _, live_raw = _request(port, "GET", "/api/product/live")
    assert live_status == 200
    live = json.loads(live_raw)
    assert live["enabled"] is False
    assert live["exchange_credentials_configured"] is False
    assert live["orders_allowed"] is False


def test_product_registry_risk_recovery_notifications_and_exports(product_server) -> None:
    port, _ = product_server
    for path in (
        "/api/product/data/registry", "/api/product/risk", "/api/product/recovery",
        "/api/product/notifications?limit=20", "/api/product/research/last",
    ):
        status, _, raw = _request(port, "GET", path)
        assert status == 200, (path, raw)
        assert json.loads(raw)["paper_only"] is True

    status, _, raw = _request(port, "GET", "/api/product/data/registry")
    registry = json.loads(raw)
    assert registry["private_credentials_required"] is False
    assert registry["authority"]["primary"] == "Bybit"

    status, content_type, raw = _request(port, "GET", "/api/product/export/paper.json")
    assert status == 200 and "application/json" in content_type
    assert json.loads(raw)["paper"]["paper_only"] is True
    status, content_type, raw = _request(port, "GET", "/api/product/export/paper.csv")
    assert status == 200 and "text/csv" in content_type and b"event_type" in raw


def test_product_rejects_live_and_unknown_write_routes(product_server) -> None:
    port, _ = product_server
    for path in ("/api/product/live/order", "/api/product/withdraw", "/api/product/exchange/credentials"):
        status, _, _ = _request(port, "POST", path, {"symbol": "BTCUSDT"})
        assert status == 405


def test_product_strategies_are_real_factory_families(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/api/product/strategies")
    assert status == 200
    payload = json.loads(raw)
    ids = {row["id"] for row in payload["families"]}
    assert ids == {"momentum", "trend_breakout", "mean_reversion"}
    assert all(row["live_execution_allowed"] is False for row in payload["families"])


def test_product_static_script_is_same_origin_only_and_has_real_product_routes(product_server) -> None:
    port, _ = product_server
    status, _, raw = _request(port, "GET", "/ui/product.js")
    assert status == 200
    script = raw.decode("utf-8")
    lowered = script.casefold()
    assert "https://" not in script
    for route in (
        "/api/product/paper/order", "/api/product/paper/auto", "/api/product/research/run",
        "/api/product/risk", "/api/product/recovery", "/api/product/data/registry",
        "/api/product/session", "/api/product/kill-switch", "/api/ai-room/message",
    ):
        assert route in script
    for forbidden in ("/api/product/live/order", "/withdraw", "/v5/order", "apisecret", "secretkey", "private_key"):
        assert forbidden not in lowered
