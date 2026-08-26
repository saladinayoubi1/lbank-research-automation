import pytest

from bybit_public_klines import BybitKlineError, normalize_closed_klines


def _payload(rows):
    return {"retCode": 0, "retMsg": "OK", "result": {"category": "spot", "list": rows}}


def test_normalizes_reverse_sorted_closed_window():
    rows = [
        ["1710000900000", "101", "103", "100", "102", "10", "1020"],
        ["1710000000000", "100", "102", "99", "101", "12", "1212"],
    ]
    result = normalize_closed_klines(
        _payload(rows),
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


class _Response:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.content = b"{}"

    def json(self):
        return self._payload


class _OfficialEndpointSession:
    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        if len(self.urls) == 1:
            return _Response(403, {})
        return _Response(200, self.payload)


def test_fetch_falls_back_only_to_the_second_official_mainnet_endpoint():
    rows = [
        ["1710000900000", "101", "103", "100", "102", "10", "1020"],
        ["1710000000000", "100", "102", "99", "101", "12", "1212"],
    ]
    session = _OfficialEndpointSession(_payload(rows))

    from bybit_public_klines import fetch_closed_klines

    result = fetch_closed_klines(
        "BTCUSDT",
        "15",
        now_ms=1710001800000,
        start_time_ms=1710000000000,
        end_time_ms=1710000900000,
        limit=2,
        session=session,
    )

    assert len(result) == 2
    assert session.urls == [
        "https://api.bybit.com/v5/market/kline",
        "https://api.bytick.com/v5/market/kline",
    ]
