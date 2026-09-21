from __future__ import annotations

import hashlib
import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from product_prospective_paper import (
    EVENT_SCHEMA,
    SCHEMA,
    SNAPSHOT_RELATIVE_PATH,
    load_prospective_paper_snapshot,
)
from product_runtime import ProductRuntime
from product_web_server import PRODUCT_UI_ROOT, build_handler
from web_dashboard import GatewayConfig


def _digest(value) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _profile(entry: float) -> dict:
    return {
        "wallet": 9996.0,
        "equity": 10234.0,
        "equity_high": 10234.0,
        "maximum_drawdown": 0.005,
        "positions": [
            {"quantity": 0.0, "average_entry": 0.0},
            {"quantity": 0.82, "average_entry": entry},
        ],
        "target_weights": [0.0, 0.2],
        "fill_count": 1,
        "asset_fill_counts": [0, 1],
        "orders": 1,
        "execution_hits": 1,
        "expected_funding_events": 1,
        "actual_funding_events": 1,
        "margin_rejections": 0,
        "liquidations": 0,
        "maximum_margin_utilization": 0.1,
        "maximum_risk_tier_utilization": 0.1,
        "fees": 2.0,
        "funding_cashflow": -1.0,
    }


def _state() -> dict:
    event_core = {
        "schema_version": EVENT_SCHEMA,
        "sequence": 1,
        "execution_utc": "2026-09-21T08:00:00Z",
        "signal_close_utc": "2026-09-21T08:00:00Z",
        "target_weights": [0.0, 0.2],
        "target_changed": True,
        "market_evidence_digest": "a" * 64,
        "source_sha": "b" * 40,
        "previous_event_digest": "0" * 64,
        "paper_only": True,
        "live_trading_enabled": False,
    }
    event = {**event_core, "event_digest": _digest(event_core)}
    core = {
        "schema_version": SCHEMA,
        "forward_id": "bybit-prospective-paper-forward-v1",
        "strategy_id": "bybit_btc_eth_regime_consensus_v1",
        "strategy_manifest_sha256": "c" * 64,
        "engine_sha256": "d" * 64,
        "start_not_before_utc": "2026-08-26T00:00:00Z",
        "last_execution_utc": "2026-09-21T08:00:00Z",
        "last_run_id": 35602187984,
        "latest_source_sha": "b" * 40,
        "completed_bar_count": 1,
        "events": [event],
        "profiles": {
            "conservative": _profile(2434.1124283384606),
            "stress": _profile(2435.021976542987),
        },
        "status": "COLLECTING",
        "decision": "collect_prospective_paper_evidence",
        "paper_only": True,
        "live_trading_enabled": False,
        "private_credentials_used": False,
        "automatic_live_promotion": False,
    }
    return {**core, "state_digest": _digest(core)}


def _write_state(root: Path, state: dict) -> Path:
    path = root / SNAPSHOT_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_valid_prospective_state_maps_open_eth_read_only(tmp_path: Path) -> None:
    _write_state(tmp_path, _state())
    snapshot = load_prospective_paper_snapshot(tmp_path)
    assert snapshot["available"] is True
    assert snapshot["read_only"] is True
    assert snapshot["paper_only"] is True
    assert snapshot["live_trading_authority"] is False
    assert snapshot["status"] == "COLLECTING"
    assert snapshot["positions"] == [{
        "symbol": "ETHUSDT",
        "side": "long",
        "quantity": 0.82,
        "signed_quantity": 0.82,
        "entry_price": 2434.1124283384606,
        "profile": "conservative",
        "source": "prospective_forward",
        "unrealized_pnl": 238.0,
    }]


def test_tampered_prospective_state_fails_closed(tmp_path: Path) -> None:
    state = _state()
    state["profiles"]["conservative"]["positions"][1]["quantity"] = 9.99
    _write_state(tmp_path, state)
    snapshot = load_prospective_paper_snapshot(tmp_path)
    assert snapshot["available"] is False
    assert snapshot["reason"] == "snapshot_invalid"
    assert snapshot["positions"] == []
    assert snapshot["live_trading_authority"] is False


def test_product_paper_endpoint_exposes_forward_without_mutating_manual_account(tmp_path: Path) -> None:
    data_root = tmp_path / "product-data" / "market"
    data_root.mkdir(parents=True)
    _write_state(data_root.parent, _state())
    runtime = ProductRuntime(tmp_path / "manual")
    probe = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        build_handler(
            data_root,
            config=GatewayConfig(mode="local", host="127.0.0.1", port=1),
            ui_root=PRODUCT_UI_ROOT,
            runtime=runtime,
        ),
    )
    port = probe.server_address[1]
    probe.server_close()
    server = ThreadingHTTPServer(
        ("127.0.0.1", port),
        build_handler(
            data_root,
            config=GatewayConfig(mode="local", host="127.0.0.1", port=port),
            ui_root=PRODUCT_UI_ROOT,
            runtime=runtime,
        ),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/api/product/paper", headers={"Host": f"127.0.0.1:{port}"})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        assert response.status == 200
        assert payload["account"]["positions"] == []
        assert payload["prospective_forward"]["positions"][0]["symbol"] == "ETHUSDT"
        assert payload["prospective_forward"]["positions"][0]["quantity"] == 0.82
        assert payload["prospective_forward"]["read_only"] is True
        assert payload["prospective_forward"]["live_trading_authority"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
