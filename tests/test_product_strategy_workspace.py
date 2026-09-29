from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from phase6_research_pipeline import bind_bybit_closed_dataset
from product_offline_runtime import OfflineDatasetStore, OfflineProductResearchRuntime
from product_offline_web_server import build_handler
from product_runtime import ProductRuntime
from product_strategy_workspace import (
    WORKSPACE_CONTRACT, StrategyWorkspace, StrategyWorkspaceError,
)
from product_web_server import PRODUCT_UI_ROOT
from web_dashboard import GatewayConfig

VALID = {
    "name": "Range failure with peer confirmation",
    "mechanism": "failed_range_break_reversal",
    "hypothesis": "A failed range break followed by independently observed peer confirmation can produce a falsifiable rebound.",
    "invalidation": "Reject when lagged aligned bars and next-open fills do not survive held-out cost stress.",
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "timeframes": ["15m", "1h", "4h"],
    "required_data": ["closed_ohlcv", "aligned_peer_ohlcv"],
}


def test_workspace_real_catalog_and_durable_owner_proposals(tmp_path: Path) -> None:
    root = tmp_path / "owner"
    w = StrategyWorkspace(root)
    first = w.snapshot()
    assert first["contract_version"] == WORKSPACE_CONTRACT
    assert len([x for x in first["catalog"] if x["kind"] == "reviewed_causal_family"]) == 7
    assert len([x for x in first["catalog"] if x["kind"] == "legacy_reference_only"]) == 3
    assert first["proposals"] == [] and first["history"] == []
    assert first["paper_only"] is True and first["live_enabled"] is False

    created = w.create(VALID)
    assert created["status"] == "requires_developer_and_independent_qa"
    assert created["execution"] == "not_implemented"
    assert created["auto_demo_promotion"] is False
    w2 = StrategyWorkspace(root)
    selected = w2.select(created["id"])
    assert selected["selection_is_not_execution"] is True
    assert w.snapshot()["selected_id"] == created["id"]
    assert w.snapshot()["proposals"] == [created]
    with pytest.raises(StrategyWorkspaceError, match="reviewed Research Agent"):
        w.selected_manual_family(created["id"])
    w2.select("composite:peer_shock_noncontagion_rebound")
    with pytest.raises(StrategyWorkspaceError, match="reviewed Research Agent"):
        w2.selected_manual_family("composite:peer_shock_noncontagion_rebound")
    with pytest.raises(StrategyWorkspaceError, match="explicitly selected"):
        w2.selected_manual_family("manual:momentum")
    w2.select("manual:momentum")
    assert w.selected_manual_family("manual:momentum") == "momentum"
    assert not list(root.rglob("*paper-events*"))


@pytest.mark.parametrize("change", [
    {"live_enabled": True},
    {"status": "paper_candidate"},
    {"name": "<>"},
    {"mechanism": ""},
    {"symbols": ["BTCUSDT", "DOGEUSDT"]},
    {"symbols": ["BTCUSDT", "BTCUSDT"]},
    {"timeframes": ["1m"]},
    {"required_data": ["fake_l2"]},
    {"required_data": ["closed_ohlcv", "closed_ohlcv"]},
    {"hypothesis": "too short"},
])
def test_workspace_rejects_unreviewed_code_execution_and_bad_schema(tmp_path: Path, change: dict) -> None:
    payload = {**VALID, **change}
    with pytest.raises(StrategyWorkspaceError):
        StrategyWorkspace(tmp_path).create(payload)
    assert not list(tmp_path.rglob("strategy-workspace.v1.json"))


def test_workspace_fail_closed_corrupt_or_symlinked_storage(tmp_path: Path) -> None:
    store = StrategyWorkspace(tmp_path / "owner")
    store.create(VALID)
    path = store.path
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(StrategyWorkspaceError, match="cannot be decoded"):
        store.snapshot()
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text('{"danger":true}', encoding="utf-8")
    try:
        path.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable")
    with pytest.raises(StrategyWorkspaceError, match="unsafe"):
        store.create(VALID)
    assert outside.read_text(encoding="utf-8") == '{"danger":true}'


def test_workspace_only_projects_real_hash_bound_ledger_numbers(tmp_path: Path) -> None:
    w = StrategyWorkspace(tmp_path)
    record = {
        "recorded_at": "2026-09-29T00:00:00Z",
        "request": {"family": "momentum", "symbol": "BTCUSDT", "timeframe": "minute15"},
        "dataset": {"binding_sha256": "c" * 64, "row_count": 120},
        "qualification": {"status": "rejected", "kill_reasons": ["negative_stress"]},
        "backtest": {"metrics": {"total_return": -.02, "max_drawdown": .08,
                                 "fill_count": 7, "win_rate": .4, "profit_factor": .8}},
        "data_mode": "offline_import",
    }
    result = w.snapshot(evidence={"runs": [record], "run_count": 1})
    assert result["history"][0]["total_return"] == -.02
    assert result["history"][0]["fill_count"] == 7
    assert result["history"][0]["independent_qa_verified"] is False
    assert result["history"][0]["pristine_oos_verified"] is False
    invalid = {**record, "dataset": {"binding_sha256": "not-bound"}}
    assert w.snapshot(evidence={"runs": [invalid], "run_count": 1})["history"] == []


def _request(port: int, method: str, path: str, payload: dict | None = None):
    conn = HTTPConnection("127.0.0.1", port, timeout=10)
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Host": f"127.0.0.1:{port}"}
    if body is not None:
        headers.update({"Content-Type": "application/json", "Content-Length": str(len(body))})
    conn.request(method, path, body=body, headers=headers)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    return res.status, json.loads(raw) if raw and res.getheader("Content-Type", "").startswith("application/json") else raw


@pytest.fixture
def server(tmp_path: Path):
    market = tmp_path / "data" / "market"
    market.mkdir(parents=True)
    runtime = ProductRuntime(tmp_path / "state", opening_cash="500")
    datasets = OfflineDatasetStore(tmp_path / "data" / "offline-datasets")
    research = OfflineProductResearchRuntime(runtime, datasets, source_sha="a" * 40)
    config = GatewayConfig(mode="local", host="127.0.0.1", port=1)
    probe = ThreadingHTTPServer(("127.0.0.1", 0), build_handler(
        market, config=config, runtime=runtime, store=datasets,
        offline_research=research, ui_root=PRODUCT_UI_ROOT,
    ))
    port = probe.server_address[1]
    probe.server_close()
    live = ThreadingHTTPServer(("127.0.0.1", port), build_handler(
        market, config=GatewayConfig(mode="local", host="127.0.0.1", port=port),
        runtime=runtime, store=datasets, offline_research=research, ui_root=PRODUCT_UI_ROOT,
    ))
    thread = threading.Thread(target=live.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, runtime, datasets
    finally:
        live.shutdown()
        live.server_close()
        thread.join(timeout=6)


def test_workspace_gateway_proposal_select_and_hard_execution_gate(server) -> None:
    port, runtime, datasets = server
    before = runtime.paper_events_path.read_bytes()
    code, status = _request(port, "GET", "/api/product/strategy-workspace")
    assert code == 200 and status["run_count"] == 0
    assert status["agent_evidence_integrated"] is False
    assert status["selected_id"] is None
    code, proposal = _request(port, "POST", "/api/product/strategy-workspace/propose", VALID)
    assert code == 200 and proposal["id"].startswith("proposal:")
    assert proposal["execution"] == "not_implemented"
    code, selected = _request(port, "POST", "/api/product/strategy-workspace/select", {"strategy_id": proposal["id"]})
    assert code == 200 and selected["selected_id"] == proposal["id"]
    code, invalid = _request(port, "POST", "/api/product/strategy-workspace/research",
                             {"strategy_id": proposal["id"], "binding_sha256": "0" * 64})
    assert code == 400
    assert b"reviewed" in json.dumps(invalid).encode()
    assert _request(port, "POST", "/api/product/strategy-workspace/propose", {**VALID, "live_enabled": True})[0] == 400
    assert _request(port, "GET", "/api/product/strategy-workspace?debug=1")[0] == 400
    code, again = _request(port, "GET", "/api/product/strategy-workspace")
    assert code == 200 and len(again["proposals"]) == 1
    assert runtime.paper_events_path.read_bytes() == before
    html_status, markup = _request(port, "GET", "/")
    assert html_status == 200 and b"/ui/product-strategy-workspace.js" in markup
    assert b"/ui/product-strategy-workspace.css" in markup
    assert _request(port, "GET", "/ui/product-strategy-workspace.js")[0] == 200
    assert _request(port, "GET", "/ui/product-strategy-workspace.css")[0] == 200


def test_manual_reference_research_is_real_offline_and_never_paper_promotion(server) -> None:
    port, runtime, datasets = server
    step = 900_000
    # Deterministic canonical Bybit bars with their actual close timestamps.
    import time
    end = ((int(time.time() * 1000) - step * 50) // step) * step
    rows = []
    for index in range(120):
        price = 100 + .13 * index + (2 if index % 11 == 0 else 0)
        open_ms = end - (119 - index) * step
        rows.append({
            "source": "Bybit", "market_type": "spot", "symbol": "BTCUSDT", "interval": "15",
            "open_time_ms": open_ms, "close_time_ms": open_ms + step - 1,
            "open": f"{price:.8f}", "high": f"{price * 1.01:.8f}",
            "low": f"{price * .99:.8f}", "close": f"{price:.8f}",
            "volume": "10", "turnover": f"{price * 10:.8f}", "closed": True,
        })
    dataset = bind_bybit_closed_dataset(
        rows, canonical_symbol="BTC/USDT", source_symbol="BTCUSDT", interval="15"
    )
    datasets.import_dataset(dataset)
    initial = runtime.paper_events_path.read_bytes()
    assert _request(port, "POST", "/api/product/strategy-workspace/select",
                    {"strategy_id": "manual:momentum"})[0] == 200
    code, out = _request(port, "POST", "/api/product/strategy-workspace/research",
                         {"strategy_id": "manual:momentum", "binding_sha256": dataset["binding_sha256"]})
    assert code == 200, out
    assert out["data_mode"] == "offline_import"
    assert out["live_execution_allowed"] is False
    code, result = _request(port, "GET", "/api/product/strategy-workspace")
    assert code == 200 and result["run_count"] == 1 and len(result["history"]) == 1
    assert result["history"][0]["family"] == "momentum"
    assert result["history"][0]["dataset_binding_sha256"] == dataset["binding_sha256"]
    assert result["history"][0]["independent_qa_verified"] is False
    assert result["history"][0]["auto_demo_promotion"] is False
    assert runtime.paper_events_path.read_bytes() == initial
