import pytest

from bybit_public_klines import (
    BybitKlineError,
    OFFICIAL_MAINNET_BASE_URLS,
    fetch_closed_klines,
    normalize_closed_klines,
)


def _payload(rows):
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": rows}}


def _rows():
    return [
        ["1710000900000", "101", "103", "100", "102", "10", "1020"],
        ["1710000000000", "100", "102", "99", "101", "12", "1212"],
    ]


class _Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}" if payload is None else b'{"retCode":0}'

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class _Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if not self.responses:
            raise AssertionError("unexpected extra request")
        return self.responses.pop(0)


def test_normalizes_reverse_sorted_closed_window():
    result = normalize_closed_klines(
        _payload(_rows()),
        symbol="BTCUSDT",
        interval="15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
    )
    assert [row["open_time_ms"] for row in result] == [1710000000000, 1710000900000]
    assert all(row["source"] == "Bybit" and row["closed"] for row in result)


def test_rejects_incomplete_window():
    rows = [["1710000000000", "100", "102", "99", "101", "12", "1212"]]
    with pytest.raises(BybitKlineError, match="incomplete"):
        normalize_closed_klines(
            _payload(rows),
            symbol="BTCUSDT",
            interval="15",
            now_ms=1710003000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
        )


def test_rejects_open_candle():
    rows = [["1710000000000", "100", "102", "99", "101", "12", "1212"]]
    with pytest.raises(BybitKlineError, match="not a closed"):
        normalize_closed_klines(
            _payload(rows),
            symbol="BTCUSDT",
            interval="15",
            now_ms=1710000500000,
            start_time_ms=1710000000000,
            end_time_ms=1710000000000,
        )


def test_fetch_uses_primary_official_mainnet_host_when_available():
    session = _Session([_Response(200, _payload(_rows()))])
    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )
    assert len(result) == 2
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]


def test_fetch_retries_only_the_second_official_mainnet_host_after_http_403():
    session = _Session([
        _Response(403),
        _Response(200, _payload(_rows())),
    ])
    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710002000000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )
    assert len(result) == 2
    assert session.urls == [
        OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline",
        OFFICIAL_MAINNET_BASE_URLS[1] + "/v5/market/kline",
    ]


def test_fetch_fails_closed_when_all_official_mainnet_hosts_are_geo_rejected():
    session = _Session([_Response(403), _Response(403)])
    with pytest.raises(BybitKlineError, match="all approved Bybit Mainnet endpoints"):
        fetch_closed_klines(
            "BTCUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert len(session.urls) == 2


def test_non_geographic_http_failure_does_not_fall_through_to_another_host():
    session = _Session([_Response(429), _Response(200, _payload(_rows()))])
    with pytest.raises(BybitKlineError, match="HTTP 429"):
        fetch_closed_klines(
            "BTCUSDT",
            "15",
            now_ms=1710002000000,
            start_time_ms=1710000000000,
            end_time_ms=1710000900000,
            limit=2,
            session=session,
        )
    assert session.urls == [OFFICIAL_MAINNET_BASE_URLS[0] + "/v5/market/kline"]
