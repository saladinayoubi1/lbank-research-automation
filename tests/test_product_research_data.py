from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from product_alternative_market import AlternativeMarketError, AlternativeMarketStore, STEPS
from product_research_reports import ResearchReportStore
from product_offline_web_server import build_handler
from product_runtime import ProductRuntime
from web_dashboard import GatewayConfig

ROOT = Path(__file__).resolve().parents[1]
NOW = 1791140400000


def public_fixture(url):
    query = parse_qs(urlsplit(url).query)
    timeframe = {"15min": "15m", "1h": "1h", "4h": "4h"}[query["granularity"][0]]
    step = STEPS[timeframe]
    end = int(query["endTime"][0])
    rows = [[str(end - step * i), "100", "103", "99", "102", "10", "1020"]
            for i in range(120, 0, -1)]
    # The real service can return its currently open candle as well.
    return {"code": "00000", "data": list(reversed(rows)) + [[str(end), "100", "103", "99", "102", "10", "1020"]]}


def test_native_closed_feed_is_separate_durable_and_never_changes_paper(tmp_path):
    owner = tmp_path / "owner" / "paper-events.jsonl"
    owner.parent.mkdir()
    owner.write_text('{"frozen":true}\n')
    old = owner.read_bytes()
    store = AlternativeMarketStore(tmp_path / "alternative", fetcher=public_fixture, clock_ms=lambda: NOW)
    for _ in range(3):
        result = store.refresh()
    assert result["state"]["feed_healthy"] is True
    assert result["state"]["successful_cycles"] == 3
    assert result["dataset_count"] == 6
    assert sum(d["row_count"] for d in result["datasets"]) == 720
    assert all(d["provider"] == "bitget" and d["fresh"] for d in result["datasets"])
    assert result["primary_execution_provider"] == "Bybit"
    assert result["paper_mutation_authority"] is False
    assert result["execution_eligible"] is False
    assert owner.read_bytes() == old
    assert AlternativeMarketStore(store.root, clock_ms=lambda: NOW).snapshot()["dataset_count"] == 6


@pytest.mark.parametrize("failure", ["gap", "duplicate", "bad_ohlc", "malformed_row", "provider_error", "denied"])
def test_failure_preserves_previous_bytes_and_never_reports_feed_healthy(tmp_path, failure):
    store = AlternativeMarketStore(tmp_path / "alternative", fetcher=public_fixture, clock_ms=lambda: NOW)
    store.refresh()
    previous = {p.name: p.read_bytes() for p in store.root.glob("latest-*.json")}
    def broken(url):
        body = public_fixture(url)
        if failure == "gap": body["data"].pop(3)
        elif failure == "duplicate": body["data"].append(body["data"][3])
        elif failure == "bad_ohlc": body["data"][3][2] = "50"
        elif failure == "malformed_row": body["data"].append(["oops"])
        elif failure == "provider_error": body["code"] = "40000"
        else: raise AlternativeMarketError("public_http_403")
        return body
    store.fetcher = broken
    result = store.refresh()
    assert result["state"]["feed_healthy"] is False
    assert result["state"]["status"] == "degraded"
    assert {p.name: p.read_bytes() for p in store.root.glob("latest-*.json")} == previous
    assert not result["execution_eligible"]


def test_cached_data_becomes_stale_and_tampered_data_is_not_projected(tmp_path):
    store = AlternativeMarketStore(tmp_path, fetcher=public_fixture, clock_ms=lambda: NOW)
    store.refresh()
    store.clock_ms = lambda: NOW + 15 * 60 * 1000
    assert not any(d["fresh"] for d in store.snapshot()["datasets"])
    path = next(tmp_path.glob("latest-*.json"))
    value = json.loads(path.read_text())
    value["rows"][0][4] = "999"
    path.write_text(json.dumps(value))
    result = store.snapshot()
    assert result["dataset_count"] == 5
    assert result["rejected"][0]["reason"] == "provider_dataset_digest_failure"


def test_polling_pauses_after_two_failures_and_startup_has_no_implicit_network(tmp_path):
    calls = []
    def denied(url):
        calls.append(url)
        raise AlternativeMarketError("public_http_403")
    store = AlternativeMarketStore(tmp_path, fetcher=denied, clock_ms=lambda: NOW, interval_seconds=0.01)
    assert calls == []
    store.set_polling(True)
    store.thread.join(timeout=3)
    assert not store.thread.is_alive()
    assert store.enabled is False
    assert len(calls) == 12
    assert store.state["status"] == "paused_after_two_failed_cycles"
    assert json.loads((tmp_path / "settings.json").read_text())["enabled"] is False


def test_reviewed_report_exact_results_and_original_rejections_are_preserved():
    result = ResearchReportStore(ROOT / "product_ui").snapshot()
    assert result["report_count"] == 2 and not result["errors"]
    a7, a9 = result["reports"]
    assert a7["original_verdict"] == "REJECTED_NO_POSITIVE_RECENT_STRESS_CELL"
    assert a9["original_verdict"] == "NOT_QUALIFIED_NO_PRISTINE_FUTURE_HOLDOUT"
    assert a7["report"]["source"]["window_days"] == 30
    assert len(a7["report"]["rows"]) == 8 and len(a9["report"]["rows"]) == 12
    assert a7["report"]["rows"][0]["net_return_pct"] == -0.52490532
    assert a9["report"]["historical_test_pristine"] is False
    assert all(r["reference_capital_usdt"] == 10000 and not r["execution_eligible"] for r in result["reports"])


def test_modified_or_duplicated_evidence_is_rejected(tmp_path):
    shutil.copytree(ROOT / "product_ui/research-reports", tmp_path / "research-reports")
    file = tmp_path / "research-reports/a7-range-failure-reversal-report.json"
    report = json.loads(file.read_text())
    report["rows"][0]["net_return_pct"] = 100
    file.write_text(json.dumps(report))
    result = ResearchReportStore(tmp_path).snapshot()
    assert result["report_count"] == 1 and result["errors"][0]["id"] == "A7"
    file.write_text('{"report_sha256":"a","report_sha256":"b"}')
    assert ResearchReportStore(tmp_path).snapshot()["report_count"] == 1


def test_http_panels_report_rows_and_mutation_validation(tmp_path):
    alternative = AlternativeMarketStore(tmp_path / "alternative", fetcher=public_fixture, clock_ms=lambda: NOW)
    server = ThreadingHTTPServer(("127.0.0.1", 0), None)
    server.RequestHandlerClass = build_handler(
        tmp_path / "market", alternative=alternative, ui_root=ROOT / "product_ui",
        config=GatewayConfig(host="127.0.0.1", port=server.server_port))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    def request(path, value=None):
        body = None if value is None else json.dumps(value).encode()
        req = Request(origin + path, data=body,
                      headers={"Content-Type": "application/json", "Origin": origin})
        return urlopen(req, timeout=5)
    try:
        with request("/") as response:
            html = response.read().decode()
            assert "/ui/product-research-data.js" in html
        with request("/api/product/research/reports") as response:
            assert json.load(response)["report_count"] == 2
        with request("/api/product/alternative-market") as response:
            assert json.load(response)["dataset_count"] == 0
        with pytest.raises(HTTPError) as error:
            request("/api/product/alternative-market/polling", {"enabled": "true"})
        assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            request("/api/product/research/reports?source=evil")
        assert error.value.code == 400
        with request("/api/product/alternative-market/refresh", {}) as response:
            assert json.load(response)["execution_eligible"] is False
        deadline = time.monotonic() + 5
        while alternative.state["status"] not in {"available", "degraded"} and time.monotonic() < deadline:
            time.sleep(0.01)
        assert alternative.snapshot()["state"]["feed_healthy"] is True
    finally:
        server.shutdown()
        server.server_close()
