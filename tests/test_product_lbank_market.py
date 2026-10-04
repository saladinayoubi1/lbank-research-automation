from __future__ import annotations

import hashlib
import json
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, urlopen

import pytest

from product_alternative_market import (
    AlternativeMarketError, AlternativeMarketStore, STEPS, public_lbank_json,
)
from product_offline_web_server import build_handler
from product_research_reports import canonical_bytes
from web_dashboard import GatewayConfig

NOW = 1791140400000


def lbank_fixture(url):
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https" and parsed.netloc == "api.lbank.info"
    assert parsed.path == "/v2/kline.do"
    assert query["symbol"][0] in {"btc_usdt", "eth_usdt"}
    assert query["size"] == ["121"]
    timeframe = {"minute15": "15m", "hour1": "1h", "hour4": "4h"}[query["type"][0]]
    step = STEPS[timeframe] // 1000
    start = int(query["time"][0])
    assert start == (NOW // STEPS[timeframe] - 120) * step
    rows = [[start + i * step, "100.000000000000001", "103", "99", "102", "0"]
            for i in range(121)]
    return {"result": "true", "error_code": 0, "data": list(reversed(rows))}


def test_lbank_native_fields_precision_and_provider_separation(tmp_path):
    bitget = AlternativeMarketStore(tmp_path / "bitget")
    lbank = AlternativeMarketStore(tmp_path / "lbank", provider="lbank",
                                   fetcher=lbank_fixture, clock_ms=lambda: NOW)
    for _ in range(3):
        result = lbank.refresh()
    assert result["provider"] == "lbank" and result["state"]["feed_healthy"]
    assert result["state"]["successful_cycles"] == 3
    assert result["dataset_count"] == 6
    assert sum(d["row_count"] for d in result["datasets"]) == 720
    assert all(d["fresh"] and d["provider"] == "lbank" for d in result["datasets"])
    assert result["primary_execution_provider"] == "Bybit"
    assert not any(result[k] for k in ("execution_eligible", "paper_mutation_authority", "live_trading_authority"))
    value = json.loads((lbank.root / "latest-BTCUSDT-15m.json").read_text())
    assert value["timestamp_unit"] == "seconds"
    assert value["rows"][0][1] == "100.000000000000001"
    assert all(len(row) == 6 for row in value["rows"])
    assert value["rows"][-1][0] * 1000 + STEPS["15m"] == value["end_exclusive_ms"]
    assert bitget.snapshot()["dataset_count"] == 0 and not bitget.root.exists()
    recovered = AlternativeMarketStore(lbank.root, provider="lbank", clock_ms=lambda: NOW)
    assert recovered.snapshot()["dataset_count"] == 6
    recovered.clock_ms = lambda: NOW + 900_000
    assert not any(d["fresh"] for d in recovered.snapshot()["datasets"])


@pytest.mark.parametrize("failure", ["gap", "duplicate", "invalid_ohlc", "negative_volume", "nonfinite",
                                     "milliseconds", "misaligned", "fractional_timestamp", "extra_field",
                                     "boolean_value", "provider_error", "http_403"])
def test_bad_lbank_data_never_overwrites_valid_cache(tmp_path, failure):
    store = AlternativeMarketStore(tmp_path, provider="lbank", fetcher=lbank_fixture, clock_ms=lambda: NOW)
    store.refresh()
    previous = {p.name: p.read_bytes() for p in tmp_path.glob("latest-*.json")}

    def broken(url):
        body = lbank_fixture(url)
        row = body["data"][4]
        if failure == "gap": body["data"].pop(4)
        elif failure == "duplicate": body["data"].append(row)
        elif failure == "invalid_ohlc": row[2] = "50"
        elif failure == "negative_volume": row[5] = "-1"
        elif failure == "nonfinite": row[1] = "NaN"
        elif failure == "milliseconds": row[0] *= 1000
        elif failure == "misaligned": row[0] += 1
        elif failure == "fractional_timestamp": row[0] = str(row[0]) + ".5"
        elif failure == "extra_field": row.append("fabricated_quote_volume")
        elif failure == "boolean_value": row[1] = True
        elif failure == "provider_error": body["result"] = "false"
        else: raise AlternativeMarketError("public_http_403")
        return body

    store.fetcher = broken
    result = store.refresh()
    assert not result["state"]["feed_healthy"]
    assert result["state"]["status"] == "degraded"
    assert {p.name: p.read_bytes() for p in tmp_path.glob("latest-*.json")} == previous


def test_provider_swapped_or_hash_modified_cache_is_rejected(tmp_path):
    store = AlternativeMarketStore(tmp_path, provider="lbank", fetcher=lbank_fixture, clock_ms=lambda: NOW)
    store.refresh()
    path = tmp_path / "latest-BTCUSDT-15m.json"
    value = json.loads(path.read_text())
    value["provider"] = "bitget"
    core = {k: v for k, v in value.items() if k != "dataset_sha256"}
    value["dataset_sha256"] = hashlib.sha256(canonical_bytes(core)).hexdigest()
    path.write_text(json.dumps(value))
    result = store.snapshot()
    assert result["dataset_count"] == 5
    assert result["rejected"][0]["reason"] == "provider_dataset_identity_failure"


def test_public_lbank_transport_preserves_numeric_decimal_text_and_bounds(monkeypatch):
    class Response:
        status = 200
        raw = b'{"result":true,"error_code":0,"data":[[1791000000,100.000000000000001,103,99,102,0]]}'
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 1_000_001
            return self.raw[:size]
    class Opener:
        def open(self, request, timeout):
            assert timeout == 6
            assert "Authorization" not in request.headers
            return Response()
    monkeypatch.setattr("product_alternative_market.urllib.request.build_opener", lambda *args: Opener())
    url = "https://api.lbank.info/v2/kline.do?symbol=btc_usdt"
    assert public_lbank_json(url)["data"][0][1] == "100.000000000000001"
    Response.raw = b'x' * 1_000_001
    with pytest.raises(AlternativeMarketError, match="oversized"):
        public_lbank_json(url)
    Response.raw = b'{"result":true,"error_code":0,"error_code":1,"data":[]}'
    with pytest.raises(AlternativeMarketError):
        public_lbank_json(url)


@pytest.mark.parametrize("url", ["http://api.lbank.info/v2/kline.do", "https://api.lbkex.com/v2/kline.do",
                                 "https://api.lbank.info.evil.test/v2/kline.do",
                                 "https://api.lbank.info/v2/create_order.do",
                                 "https://user@api.lbank.info/v2/kline.do",
                                 "https://api.lbank.info/v2/kline.do#fragment"])
def test_lbank_transport_rejects_other_endpoints_before_network(url):
    with pytest.raises(AlternativeMarketError, match="endpoint_rejected"):
        public_lbank_json(url)


def test_lbank_polling_failure_is_independent_and_stop_does_not_duplicate_workers(tmp_path):
    bitget = AlternativeMarketStore(tmp_path / "bitget")
    calls = []
    def denied(url):
        calls.append(url)
        raise AlternativeMarketError("public_http_403")
    store = AlternativeMarketStore(tmp_path / "lbank", provider="lbank", fetcher=denied,
                                   clock_ms=lambda: NOW, interval_seconds=0.01)
    assert calls == []
    store.set_polling(True)
    store.thread.join(timeout=3)
    assert not store.enabled and not store.thread.is_alive()
    assert len(calls) == 12 and store.state["status"] == "paused_after_two_failed_cycles"
    assert json.loads((store.root / "settings.json").read_text())["enabled"] is False
    assert not bitget.root.exists()
    entered, release = threading.Event(), threading.Event()
    def delayed(url):
        entered.set()
        assert release.wait(3)
        return lbank_fixture(url)
    store.fetcher = delayed
    store.set_polling(True)
    assert entered.wait(3)
    worker = store.thread
    store.set_polling(False)
    assert store.set_polling(True)["status"] == "stopping"
    assert store.thread is worker and not store.enabled
    release.set()
    worker.join(timeout=3)
    assert not worker.is_alive()


def test_lbank_http_controls_are_separate_authenticated_and_preserve_paper(tmp_path):
    store = AlternativeMarketStore(tmp_path / "lbank", provider="lbank", fetcher=lbank_fixture,
                                   clock_ms=lambda: NOW)
    bitget = AlternativeMarketStore(tmp_path / "bitget", clock_ms=lambda: NOW)
    server = ThreadingHTTPServer(("127.0.0.1", 0), None)
    server.RequestHandlerClass = build_handler(
        tmp_path / "market", alternative=bitget, lbank=store,
        config=GatewayConfig(host="127.0.0.1", port=server.server_port))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    def request(path, payload=None, request_origin=None):
        req = Request(origin + path, data=None if payload is None else json.dumps(payload).encode(),
                      headers={"Content-Type": "application/json", "Origin": request_origin or origin})
        with urlopen(req, timeout=5) as response:
            return json.load(response)
    try:
        before = request("/api/product/paper")
        assert request("/api/product/lbank-market")["dataset_count"] == 0
        for path, body in [("/api/product/lbank-market?provider=bitget", None),
                           ("/api/product/lbank-market/polling", {"enabled": "true"}),
                           ("/api/product/lbank-market/refresh", {"url": "https://evil.test"})]:
            with pytest.raises(HTTPError) as error:
                request(path, body)
            assert error.value.code == 400
        with pytest.raises(HTTPError) as error:
            request("/api/product/lbank-market/refresh", {}, "https://evil.test")
        assert error.value.code == 403
        assert request("/api/product/lbank-market/refresh", {})["status"] == "started"
        deadline = time.monotonic() + 3
        while store.state["status"] not in {"available", "degraded"} and time.monotonic() < deadline:
            time.sleep(0.01)
        assert request("/api/product/lbank-market")["state"]["feed_healthy"]
        assert request("/api/product/alternative-market")["dataset_count"] == 0
        assert request("/api/product/lbank-market/polling", {"enabled": True})["status"] == "started"
        assert not bitget.enabled
        assert request("/api/product/lbank-market/polling", {"enabled": False})["status"] == "stopped"
        after = request("/api/product/paper")
        for key in ("event_count", "head_event_digest", "session_signal_count", "account"):
            assert before[key] == after[key]
    finally:
        store.set_polling(False)
        if store.thread: store.thread.join(timeout=3)
        server.shutdown()
        server.server_close()


def test_polling_opt_in_survives_restart(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "settings.json").write_text('{"enabled":true}')
    called = threading.Event()
    def fetcher(url):
        called.set()
        return lbank_fixture(url)
    store = AlternativeMarketStore(tmp_path, provider="lbank", fetcher=fetcher, clock_ms=lambda: NOW)
    try:
        assert called.wait(3) and store.enabled
    finally:
        store.set_polling(False)
        store.thread.join(timeout=3)
