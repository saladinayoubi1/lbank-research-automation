from __future__ import annotations

import json

import pytest

from binance_public_klines import BinanceKlineError, fetch_closed_klines, normalize_closed_klines


NOW_MS = 2_000_000
INTERVAL_MS = 900_000


def _row(open_time: int = 900_000, close_time: int | None = None) -> list[object]:
    if close_time is None:
        close_time = open_time + INTERVAL_MS - 1
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
            "open_time_ms": 900_000,
            "close_time_ms": 1_799_999,
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
        normalize_closed_klines([_row(open_time=1_800_000)], symbol="BTCUSDT", interval="15m", now_ms=NOW_MS)


def test_rejects_duplicate_open_time() -> None:
    with pytest.raises(BinanceKlineError, match="duplicate candle open time"):
        normalize_closed_klines([_row(), _row()], symbol="BTCUSDT", interval="15m", now_ms=NOW_MS)


def test_rejects_non_chronological_payload() -> None:
    with pytest.raises(BinanceKlineError, match="strictly chronological"):
        normalize_closed_klines(
            [_row(open_time=900_000), _row(open_time=0)],
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


def test_rejects_off_grid_open_time() -> None:
    with pytest.raises(BinanceKlineError, match="off the 15m grid"):
        normalize_closed_klines(
            [_row(open_time=900_001, close_time=1_800_000)],
            symbol="BTCUSDT",
            interval="15m",
            now_ms=2_000_001,
        )


def test_rejects_wrong_granularity_even_when_closed_and_ordered() -> None:
    with pytest.raises(BinanceKlineError, match="does not match requested 15m duration"):
        normalize_closed_klines(
            [_row(open_time=0, close_time=3_599_999)],
            symbol="BTCUSDT",
            interval="15m",
            now_ms=4_000_000,
        )


def test_complete_window_rejects_truncated_payload() -> None:
    with pytest.raises(BinanceKlineError, match="incomplete or substituted"):
        normalize_closed_klines(
            [_row(open_time=0)],
            symbol="BTCUSDT",
            interval="15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=900_000,
            require_complete_window=True,
        )


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
        start_time_ms=900_000,
        end_time_ms=900_000,
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
        "startTime": 900_000,
        "endTime": 900_000,
    }


def test_fetch_rejects_non_200_response() -> None:
    session = _Session(_Response({"code": -1}, status_code=429))
    with pytest.raises(BinanceKlineError, match="HTTP 429"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=900_000,
            end_time_ms=900_000,
            session=session,
        )


def test_fetch_rejects_invalid_limit_before_network() -> None:
    session = _Session(_Response([_row()]))
    with pytest.raises(BinanceKlineError, match="limit must be between"):
        fetch_closed_klines("BTCUSDT", "15m", now_ms=NOW_MS, limit=1001, session=session)
    assert session.calls == []


def test_fetch_requires_explicit_window_before_network() -> None:
    session = _Session(_Response([_row()]))
    with pytest.raises(BinanceKlineError, match="start_time_ms must be"):
        fetch_closed_klines("BTCUSDT", "15m", now_ms=NOW_MS, session=session)
    assert session.calls == []


def test_fetch_rejects_reversed_time_range_before_network() -> None:
    session = _Session(_Response([_row()]))
    with pytest.raises(BinanceKlineError, match="cannot be before"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=900_000,
            end_time_ms=0,
            session=session,
        )
    assert session.calls == []


def test_fetch_rejects_window_larger_than_single_complete_page() -> None:
    session = _Session(_Response([_row(open_time=0), _row(open_time=900_000)]))
    with pytest.raises(BinanceKlineError, match="deterministic pagination is required"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=900_000,
            limit=1,
            session=session,
        )
    assert session.calls == []


def test_fetch_rejects_window_that_includes_open_candle() -> None:
    session = _Session(_Response([_row(open_time=1_800_000)]))
    with pytest.raises(BinanceKlineError, match="open or incomplete candle"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=1_800_000,
            end_time_ms=1_800_000,
            session=session,
        )
    assert session.calls == []


def test_fetch_rejects_stale_replayed_well_formed_page() -> None:
    session = _Session(_Response([_row(open_time=0)]))
    with pytest.raises(BinanceKlineError, match="precedes requested start_time_ms"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=900_000,
            end_time_ms=900_000,
            session=session,
        )


def test_fetch_rejects_out_of_window_page_substitution() -> None:
    session = _Session(_Response([_row(open_time=1_800_000)]))
    with pytest.raises(BinanceKlineError, match="exceeds requested end_time_ms"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=3_000_000,
            start_time_ms=900_000,
            end_time_ms=900_000,
            session=session,
        )


def test_fetch_rejects_truncated_response_for_requested_window() -> None:
    session = _Session(_Response([_row(open_time=0)]))
    with pytest.raises(BinanceKlineError, match="incomplete or substituted"):
        fetch_closed_klines(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=900_000,
            limit=2,
            session=session,
        )
