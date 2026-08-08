from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import requests

BASE_URL = "https://api.binance.com"
KLINES_PATH = "/api/v3/klines"
INTERVAL_MS = {"15m": 15 * 60 * 1000, "1h": 60 * 60 * 1000, "4h": 4 * 60 * 60 * 1000}
SUPPORTED_INTERVALS = set(INTERVAL_MS)
MAX_RESPONSE_BYTES = 2_000_000
MAX_LIMIT = 1000


class BinanceKlineError(RuntimeError):
    pass


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or not normalized.isalnum() or len(normalized) > 32:
        raise BinanceKlineError("unsupported Binance symbol")
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise BinanceKlineError(f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BinanceKlineError(f"{field} is malformed") from exc
    if not parsed.is_finite():
        raise BinanceKlineError(f"{field} must be finite")
    return parsed


def _validate_bound(name: str, value: int | None) -> int:
    if value is None or not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise BinanceKlineError(f"{name} must be a non-negative integer")
    return value


def _expected_open_times(start_time_ms: int, end_time_ms: int, interval_ms: int) -> list[int]:
    first = ((start_time_ms + interval_ms - 1) // interval_ms) * interval_ms
    last = (end_time_ms // interval_ms) * interval_ms
    if first > last:
        return []
    return list(range(first, last + 1, interval_ms))


def normalize_closed_klines(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    require_complete_window: bool = False,
) -> list[dict[str, Any]]:
    normalized_symbol = _normalize_symbol(symbol)
    if interval not in SUPPORTED_INTERVALS:
        raise BinanceKlineError("unsupported Binance interval")
    if not isinstance(now_ms, int) or isinstance(now_ms, bool) or now_ms <= 0:
        raise BinanceKlineError("now_ms must be a positive integer")
    if not isinstance(require_complete_window, bool):
        raise BinanceKlineError("require_complete_window must be boolean")
    if not isinstance(payload, list):
        raise BinanceKlineError("Binance kline payload must be a list")

    interval_ms = INTERVAL_MS[interval]
    if start_time_ms is not None:
        _validate_bound("start_time_ms", start_time_ms)
    if end_time_ms is not None:
        _validate_bound("end_time_ms", end_time_ms)
    if start_time_ms is not None and end_time_ms is not None and end_time_ms < start_time_ms:
        raise BinanceKlineError("end_time_ms cannot be before start_time_ms")
    if require_complete_window and (start_time_ms is None or end_time_ms is None):
        raise BinanceKlineError("complete-window validation requires start_time_ms and end_time_ms")

    normalized: list[dict[str, Any]] = []
    seen_open_times: set[int] = set()
    previous_open_time: int | None = None

    for index, row in enumerate(payload):
        if not isinstance(row, list) or len(row) < 7:
            raise BinanceKlineError(f"row {index} is malformed")
        open_time, raw_open, raw_high, raw_low, raw_close, raw_volume, close_time = row[:7]
        if not isinstance(open_time, int) or isinstance(open_time, bool):
            raise BinanceKlineError(f"row {index} open time is malformed")
        if not isinstance(close_time, int) or isinstance(close_time, bool):
            raise BinanceKlineError(f"row {index} close time is malformed")
        if open_time < 0 or close_time <= open_time:
            raise BinanceKlineError(f"row {index} timestamp range is invalid")
        if open_time % interval_ms != 0:
            raise BinanceKlineError(f"row {index} open time is off the {interval} grid")
        if close_time != open_time + interval_ms - 1:
            raise BinanceKlineError(f"row {index} does not match requested {interval} duration")
        if close_time >= now_ms:
            raise BinanceKlineError(f"row {index} is not a closed historical candle")
        if start_time_ms is not None and open_time < start_time_ms:
            raise BinanceKlineError(f"row {index} precedes requested start_time_ms")
        if end_time_ms is not None and open_time > end_time_ms:
            raise BinanceKlineError(f"row {index} exceeds requested end_time_ms")
        if open_time in seen_open_times:
            raise BinanceKlineError(f"duplicate candle open time: {open_time}")
        if previous_open_time is not None and open_time <= previous_open_time:
            raise BinanceKlineError("Binance klines must be strictly chronological")

        open_price = _decimal(raw_open, "open")
        high_price = _decimal(raw_high, "high")
        low_price = _decimal(raw_low, "low")
        close_price = _decimal(raw_close, "close")
        volume = _decimal(raw_volume, "volume")

        if min(open_price, high_price, low_price, close_price) <= 0:
            raise BinanceKlineError(f"row {index} prices must be positive")
        if volume < 0:
            raise BinanceKlineError(f"row {index} volume cannot be negative")
        if high_price < max(open_price, close_price, low_price):
            raise BinanceKlineError(f"row {index} high violates OHLC bounds")
        if low_price > min(open_price, close_price, high_price):
            raise BinanceKlineError(f"row {index} low violates OHLC bounds")

        normalized.append(
            {
                "source": "Binance",
                "market_type": "spot",
                "symbol": normalized_symbol,
                "interval": interval,
                "open_time_ms": open_time,
                "close_time_ms": close_time,
                "open": str(open_price),
                "high": str(high_price),
                "low": str(low_price),
                "close": str(close_price),
                "volume": str(volume),
                "closed": True,
            }
        )
        seen_open_times.add(open_time)
        previous_open_time = open_time

    if require_complete_window:
        assert start_time_ms is not None and end_time_ms is not None
        expected_open_times = _expected_open_times(start_time_ms, end_time_ms, interval_ms)
        actual_open_times = [candle["open_time_ms"] for candle in normalized]
        if actual_open_times != expected_open_times:
            raise BinanceKlineError("Binance kline response is incomplete or substituted for the requested window")

    return normalized


def fetch_closed_klines(
    symbol: str,
    interval: str,
    *,
    now_ms: int,
    start_time_ms: int | None = None,
    end_time_ms: int | None = None,
    limit: int = 1000,
    timeout_seconds: float = 30.0,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Fetch one deterministic, complete closed-candle window.

    This bounded adapter intentionally does not expose an ambiguous best-effort page API.
    Both time bounds are required, the requested interval grid is derived locally, and
    the response must contain exactly the expected open timestamps. Larger windows must
    be split by a future deterministic paginator rather than silently accepted as partial.
    """
    normalized_symbol = _normalize_symbol(symbol)
    if interval not in SUPPORTED_INTERVALS:
        raise BinanceKlineError("unsupported Binance interval")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise BinanceKlineError(f"limit must be between 1 and {MAX_LIMIT}")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise BinanceKlineError("timeout_seconds must be positive")

    start_time_ms = _validate_bound("start_time_ms", start_time_ms)
    end_time_ms = _validate_bound("end_time_ms", end_time_ms)
    if end_time_ms < start_time_ms:
        raise BinanceKlineError("end_time_ms cannot be before start_time_ms")

    interval_ms = INTERVAL_MS[interval]
    expected_open_times = _expected_open_times(start_time_ms, end_time_ms, interval_ms)
    if not expected_open_times:
        raise BinanceKlineError("requested window contains no candle open on the interval grid")
    if len(expected_open_times) > limit:
        raise BinanceKlineError("requested window exceeds one complete Binance page; deterministic pagination is required")
    if expected_open_times[-1] + interval_ms - 1 >= now_ms:
        raise BinanceKlineError("requested window includes an open or incomplete candle")

    params: dict[str, Any] = {
        "symbol": normalized_symbol,
        "interval": interval,
        "limit": limit,
        "startTime": start_time_ms,
        "endTime": end_time_ms,
    }

    client = session or requests.Session()
    response = client.get(
        f"{BASE_URL}{KLINES_PATH}",
        params=params,
        timeout=timeout_seconds,
        allow_redirects=False,
        headers={"Accept": "application/json"},
    )
    if response.status_code != 200:
        raise BinanceKlineError(f"Binance kline request failed with HTTP {response.status_code}")
    content = response.content
    if len(content) > MAX_RESPONSE_BYTES:
        raise BinanceKlineError("Binance kline response exceeds size limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BinanceKlineError("Binance kline response is not valid JSON") from exc
    return normalize_closed_klines(
        payload,
        symbol=normalized_symbol,
        interval=interval,
        now_ms=now_ms,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        require_complete_window=True,
    )
