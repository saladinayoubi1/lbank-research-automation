from __future__ import annotations

from typing import Any

from binance_public_klines import BinanceKlineError, INTERVAL_MS, MAX_LIMIT, fetch_closed_klines


MAX_PAGES = 100


def fetch_closed_klines_paginated(
    symbol: str,
    interval: str,
    *,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    page_limit: int = MAX_LIMIT,
    max_pages: int = MAX_PAGES,
    timeout_seconds: float = 30.0,
    session: Any | None = None,
) -> list[dict[str, Any]]:
    """Fetch a bounded historical window as deterministic complete pages.

    Pages are derived locally from the requested interval grid. Every page is fetched
    through the existing fail-closed single-page adapter, and the aggregate result must
    contain exactly the expected ordered timestamp set. No best-effort partial result is
    returned.
    """
    if interval not in INTERVAL_MS:
        raise BinanceKlineError("unsupported Binance interval")
    if not isinstance(start_time_ms, int) or isinstance(start_time_ms, bool) or start_time_ms < 0:
        raise BinanceKlineError("start_time_ms must be a non-negative integer")
    if not isinstance(end_time_ms, int) or isinstance(end_time_ms, bool) or end_time_ms < 0:
        raise BinanceKlineError("end_time_ms must be a non-negative integer")
    if end_time_ms < start_time_ms:
        raise BinanceKlineError("end_time_ms cannot be before start_time_ms")
    if not isinstance(page_limit, int) or isinstance(page_limit, bool) or not 1 <= page_limit <= MAX_LIMIT:
        raise BinanceKlineError(f"page_limit must be between 1 and {MAX_LIMIT}")
    if not isinstance(max_pages, int) or isinstance(max_pages, bool) or max_pages < 1:
        raise BinanceKlineError("max_pages must be a positive integer")
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise BinanceKlineError("now_ms must be a positive integer")

    interval_ms = INTERVAL_MS[interval]
    first_open = ((start_time_ms + interval_ms - 1) // interval_ms) * interval_ms
    last_open = (end_time_ms // interval_ms) * interval_ms
    if first_open > last_open:
        raise BinanceKlineError("requested window contains no candle open on the interval grid")
    if last_open + interval_ms - 1 >= now_ms:
        raise BinanceKlineError("requested window includes an open or incomplete candle")

    expected_count = ((last_open - first_open) // interval_ms) + 1
    required_pages = (expected_count + page_limit - 1) // page_limit
    if required_pages > max_pages:
        raise BinanceKlineError("requested window exceeds bounded pagination budget")

    result: list[dict[str, Any]] = []
    page_start = first_open
    while page_start <= last_open:
        page_last_index = min(page_limit - 1, (last_open - page_start) // interval_ms)
        page_end = page_start + page_last_index * interval_ms
        page = fetch_closed_klines(
            symbol,
            interval,
            now_ms=now_ms,
            start_time_ms=page_start,
            end_time_ms=page_end,
            limit=page_limit,
            timeout_seconds=timeout_seconds,
            session=session,
        )
        result.extend(page)
        page_start = page_end + interval_ms

    actual_open_times = [int(candle["open_time_ms"]) for candle in result]
    expected_open_times = list(range(first_open, last_open + 1, interval_ms))
    if actual_open_times != expected_open_times:
        raise BinanceKlineError("paginated Binance response is incomplete, duplicated, or substituted")

    return result
