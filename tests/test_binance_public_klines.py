from __future__ import annotations

import json

import pytest

from binance_public_klines import BinanceKlineError, fetch_closed_klines, normalize_closed_klines


NOW_MS = 2_000_000


def _row(open_time: int = 1_000_000, close_time: int = 1_899_999) -> list[object]:
    return [
        open_time,
        "100.0",
        "110.0",
        "90.0",
        "105.0",
        "12.5",
        close_time,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


def test_normalizes_closed_spot_kline_with_provenance() -> None:
    result = normalize_closed_klines([_row()], symbol="btcusdt", interval="15m", now_ms=NOW_MS)
    assert result == [
        {
            "source": "Binance",
            "market_type": "spot",
            "symbol": "BTCUSDT",
            "interval": "15m",
            "open_time_ms": 1_000_000,
            "close_time_ms": 1_899_999,
            "open": "100.0",
            "high": "110.0",
            "low": "90.0",
            "close": "105.0",
            "volume": "12.5",
            "closed": True,
        }
    ]


def test_rejects_open_or_incomplete_candle() -> None:
    with pytest.raises(BinanceKlineError, match="not a closed historical candle"):
        normalize_closed_klines([_row(close_time=NOW_MS)], symbol="BTCUSDT", interval="15m", now_ms=NOW_MS)


def test_rejects_duplicate_open_time() -> None:
    with pytest.raises(BinanceKlineError, match="duplicate candle open time"):
        normalize_closed_klines([_row(), _row()], symbol="BTCUSDT", interval="15m", now_ms=NOW_MS)


def test_rejects_non_chronological_payload() -> None:
    with pytest.raises(BinanceKlineError, match="strictly chronological"):
        normalize_closed_klines(
            [_row(open_time=1_100_000, close_time=1_199_999), _row(open_time=1_000_000, close_time=1_099_999)],
            symbol="BTCUSDT",
            interval="15m",
            now_ms=NOW_MS,
        )


def test_rejects_invalid_ohlc_bounds() -> None:
    row = _row()
    row[2] = "99"
    with pytest.raises(BinanceKlineError, match="high violates OHLC bounds"):
        normalize_closed_klines([row], symbol="BTCUSDT", interval="15m", now_ms=NOW_MS)


def test_rejects_unknown_interval() -> None:
    with pytest.raises(BinanceKlineError, match="unsupported Binance interval"):
        normalize_closed_klines([_row()], symbol="BTCUSDT", interval="1m", now_ms=NOW_MS)


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> object:
        return self._payload


class _Session:
    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append((url, kwargs))
        return self.response


def test_fetch_uses_fixed_public_endpoint_without_redirects_or_credentials() -> None:
    session = _Session(_Response([_row()]))
    result = fetch_closed_klines(
        "BTCUSDT",
        "15m",
        now_ms=NOW_MS,
        start_time_ms=1,
        end_time_ms=100,
        limit=10,
        session=session,
    )
    assert result[0]["source"] == "Binance"
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == "https://api.binance.com/api/v3/klines"
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"] == {"Accept": "application/json"}
    assert kwargs["params"] == {
        "symbol": "BTCUSDT",
        "interval": "15m",
        "limit": 10,
        "startTime": 1,
        "endTime": 100,
    }


def test_fetch_rejects_non_200_response() -> None:
    session = _Session(_Response({"code": -1}, status_code=429))
    with pytest.raises(BinanceKlineError, match="HTTP 429"):
        fetch_closed_klines("BTCUSDT", "15m", now_ms=NOW_MS, session=session)


def test_fetch_rejects_invalid_limit_before_network() -> None:
    session = _Session(_Response([_row()]))
    with pytest.raises(BinanceKlineError, match="limit must be between"):
        fetch_closed_klines("BTCUSDT", "15m", now_ms=NOW_MS, limit=1001, session=session)
    assert session.calls == []


def test_fetch_rejects_reversed_time_range_before_network() -> None:
    session = _Session(_Response([_row()]))
    with pytest.raises(BinanceKlineError, match="cannot be before"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=100,
            end_time_ms=99,
            session=session,
        )
    assert session.calls == []
