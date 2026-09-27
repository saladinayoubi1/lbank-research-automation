from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import pytest

from product_market_diagnostics import MarketProbeInputError, probe_primary_spot

STEP = 14_400_000
NOW = 30 * STEP + STEP // 2
REGISTRY = {
    "mappings": [{
        "canonical_symbol": "BTC/USDT", "market_category": "spot",
        "timeframe": "4h", "finality": "closed_only",
        "sources": [{
            "exchange": "Bybit", "role": "primary", "status": "compatible",
            "symbol": "BTCUSDT", "category": "spot",
        }],
    }]
}


def _rows(*, newest=30, count=12):
    return [
        [str(n * STEP), "100", "110", "90", "101", "2", "202"]
        for n in range(newest, newest - count, -1)
    ]


def _response(rows=None, *, symbol="BTCUSDT", category="spot", ret=0):
    return json.dumps({
        "retCode": ret, "retMsg": "OK" if ret == 0 else "denied",
        "result": {"symbol": symbol, "category": category, "list": _rows() if rows is None else rows},
    }).encode()


def _probe(fetcher, *, symbol="BTCUSDT", timeframe="4h", registry=REGISTRY):
    return probe_primary_spot(
        symbol=symbol, timeframe=timeframe, registry=registry,
        now_ms=NOW, fetcher=fetcher,
    )


def test_safely_excludes_current_unconfirmed_open_candle() -> None:
    rows = _rows()
    rows[0][4] = "999999"  # never publish the current in-progress close
    observed = []
    def fetch(url, timeout):
        observed.append((url, timeout))
        return _response(rows)
    result = _probe(fetch)
    assert observed == [(
        "https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=240&limit=12",
        6.0,
    )]
    assert result["status"] == "verified_closed_candles"
    assert result["reason_code"] == "source_probe_passed"
    assert result["last_close_price"] == "101"
    assert result["lag_bars"] == 0
    assert result["last_closed_at_utc"].endswith("Z")
    assert result["closed_bars_verified"] == 5
    assert result["execution_eligible"] is False
    assert result["paper_only"] is True and result["read_only"] is True
    assert result["dataset_written"] is False


@pytest.mark.parametrize("code,expected", [
    (403, "public_http_403_access_denied"),
    (429, "public_http_429_rate_limited"),
    (500, "public_http_failure"),
])
def test_reports_http_failure_without_fabricating_market_price(code: int, expected: str) -> None:
    def fetch(_url, _timeout):
        raise HTTPError("https://api.bybit.com/v5/market/kline", code, "denied", {}, io.BytesIO())
    result = _probe(fetch)
    assert (result["status"], result["http_status"], result["reason_code"]) == ("unavailable", code, expected)
    assert result["last_close_price"] is None
    assert result["execution_eligible"] is False


def test_network_or_tls_failure_is_not_an_offline_fallback() -> None:
    result = _probe(lambda *_: (_ for _ in ()).throw(URLError("offline")))
    assert result["reason_code"] == "public_transport_unavailable"
    assert result["status"] == "unavailable"
    assert result["last_close_price"] is None


def test_rejects_recent_gap_even_when_the_last_closed_candle_is_fresh() -> None:
    rows = _rows()
    rows.remove(next(row for row in rows if row[0] == str(27 * STEP)))
    result = _probe(lambda *_: _response(rows))
    assert result["status"] == "integrity_failed"
    assert result["reason_code"] == "recent_closed_candle_gap"
    assert result["last_close_price"] is None


def test_stale_bars_fail_closed_without_publishing_old_price() -> None:
    result = _probe(lambda *_: _response(_rows(newest=25)))
    assert result["status"] == "stale"
    assert result["lag_bars"] == 4
    assert result["last_close_price"] is None
    assert result["last_closed_at_utc"]


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[1].__setitem__(2, "99"),  # high under close
    lambda rows: rows[1].__setitem__(4, "NaN"),
    lambda rows: rows[1].__setitem__(5, "-1"),
    lambda rows: rows[1].__setitem__(0, str(29 * STEP + 1)),
    lambda rows: rows.insert(2, rows[1][:]),  # duplicate
])
def test_rejects_malformed_price_and_timestamp_semantics(mutation) -> None:
    rows = _rows()
    mutation(rows)
    result = _probe(lambda *_: _response(rows))
    assert result["status"] == "integrity_failed"
    assert result["last_close_price"] is None


@pytest.mark.parametrize("bad", [
    _response(symbol="ETHUSDT"),
    _response(category="linear"),
    _response(ret=10001),
    b"not-json",
    b"x" * 96001,
    _response(rows=_rows(count=2)),
])
def test_no_fabricated_feed_on_malformed_or_wrong_source(bad: bytes) -> None:
    result = _probe(lambda *_: bad)
    assert result["status"] != "verified_closed_candles"
    assert result["last_close_price"] is None


@pytest.mark.parametrize("symbol,timeframe,registry", [
    ("ETHUSDT", "4h", REGISTRY),
    ("BTCUSDT", "1h", REGISTRY),
    ("BTCUSDT&interval=15", "4h", REGISTRY),
    ("BTCUSDT", "4h", {"mappings": []}),
])
def test_input_rejected_before_network(symbol: str, timeframe: str, registry) -> None:
    called = []
    def fetch(*_):
        called.append(True)
        return _response()
    with pytest.raises(MarketProbeInputError):
        _probe(fetch, symbol=symbol, timeframe=timeframe, registry=registry)
    assert not called
