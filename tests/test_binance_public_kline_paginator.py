from __future__ import annotations

import json

import pytest

from binance_public_kline_paginator import fetch_closed_klines_paginated
from binance_public_klines import BinanceKlineError


INTERVAL_MS = 900_000
NOW_MS = 10_000_000


def _row(open_time: int) -> list[object]:
    return [
        open_time,
        "100.0",
        "110.0",
        "90.0",
        "105.0",
        "12.5",
        open_time + INTERVAL_MS - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


class _Response:
    def __init__(self, payload: object) -> None:
        self._payload = payload
        self.status_code = 200
        self.content = json.dumps(payload).encode("utf-8")

    def json(self) -> object:
        return self._payload


class _PagedSession:
    def __init__(self, pages: list[list[object]]) -> None:
        self.pages = list(pages)
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, **kwargs: object) -> _Response:
        self.calls.append({"url": url, **kwargs})
        if not self.pages:
            raise AssertionError("unexpected extra page request")
        return _Response(self.pages.pop(0))


def test_fetches_multiple_complete_pages_in_order() -> None:
    session = _PagedSession(
        [
            [_row(0), _row(900_000)],
            [_row(1_800_000), _row(2_700_000)],
            [_row(3_600_000)],
        ]
    )
    result = fetch_closed_klines_paginated(
        "BTCUSDT",
        "15m",
        now_ms=NOW_MS,
        start_time_ms=0,
        end_time_ms=3_600_000,
        page_limit=2,
        session=session,
    )
    assert [row["open_time_ms"] for row in result] == [0, 900_000, 1_800_000, 2_700_000, 3_600_000]
    assert len(session.calls) == 3
    assert [call["params"]["startTime"] for call in session.calls] == [0, 1_800_000, 3_600_000]
    assert [call["params"]["endTime"] for call in session.calls] == [900_000, 2_700_000, 3_600_000]


def test_rejects_truncated_middle_page() -> None:
    session = _PagedSession(
        [
            [_row(0), _row(900_000)],
            [_row(1_800_000)],
        ]
    )
    with pytest.raises(BinanceKlineError, match="incomplete or substituted"):
        fetch_closed_klines_paginated(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=2_700_000,
            page_limit=2,
            session=session,
        )


def test_rejects_page_budget_before_network() -> None:
    session = _PagedSession([])
    with pytest.raises(BinanceKlineError, match="bounded pagination budget"):
        fetch_closed_klines_paginated(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=3_600_000,
            page_limit=1,
            max_pages=4,
            session=session,
        )
    assert session.calls == []


def test_rejects_window_with_open_candle_before_network() -> None:
    session = _PagedSession([])
    with pytest.raises(BinanceKlineError, match="open or incomplete candle"):
        fetch_closed_klines_paginated(
            "BTCUSDT",
            "15m",
            now_ms=1_000_000,
            start_time_ms=900_000,
            end_time_ms=900_000,
            session=session,
        )
    assert session.calls == []


def test_rejects_invalid_page_limit_before_network() -> None:
    session = _PagedSession([])
    with pytest.raises(BinanceKlineError, match="page_limit must be between"):
        fetch_closed_klines_paginated(
            "BTCUSDT",
            "15m",
            now_ms=NOW_MS,
            start_time_ms=0,
            end_time_ms=0,
            page_limit=0,
            session=session,
        )
    assert session.calls == []
