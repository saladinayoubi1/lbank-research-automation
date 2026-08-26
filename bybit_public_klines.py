from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import requests

BASE_URLS = ("https://api.bybit.com", "https://api.bytick.com")
BASE_URL = BASE_URLS[0]
KLINES_PATH = "/v5/market/kline"
INTERVAL_MS = {"15": 15 * 60 * 1000, "60": 60 * 60 * 1000, "240": 4 * 60 * 60 * 1000}
SUPPORTED_INTERVALS = set(INTERVAL_MS)
MAX_LIMIT = 1000
MAX_RESPONSE_BYTES = 2_000_000


class BybitKlineError(RuntimeError):
    pass


def _normalize_symbol(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if not normalized or not normalized.isalnum() or len(normalized) > 32:
        raise BybitKlineError("unsupported Bybit symbol")
    return normalized


def _decimal(value: Any, field: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise BybitKlineError(f"{field} must be numeric")
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BybitKlineError(f"{field} is malformed") from exc
    if not parsed.is_finite():
        raise BybitKlineError(f"{field} must be finite")
    return parsed


def _expected_open_times(start_ms: int, end_ms: int, interval_ms: int) -> list[int]:
    first = ((start_ms + interval_ms - 1) // interval_ms) * interval_ms
    last = (end_ms // interval_ms) * interval_ms
    if first > last:
        return []
    return list(range(first, last + 1, interval_ms))


def normalize_closed_klines(
    payload: Any,
    *,
    symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    require_complete_window: bool = True,
) -> list[dict[str, Any]]:
    normalized_symbol = _normalize_symbol(symbol)
    if interval not in SUPPORTED_INTERVALS:
        raise BybitKlineError("unsupported Bybit interval")
    if not isinstance(payload, dict):
        raise BybitKlineError("Bybit payload must be an object")
    if payload.get("retCode") != 0:
        raise BybitKlineError(f"Bybit request failed: retCode={payload.get('retCode')}")

    result = payload.get("result")
    rows = result.get("list") if isinstance(result, dict) else None
    if not isinstance(rows, list):
        raise BybitKlineError("Bybit result.list must be a list")

    interval_ms = INTERVAL_MS[interval]
    normalized: list[dict[str, Any]] = []
    seen: set[int] = set()

    # Bybit documents reverse-sorted kline pages. Normalize to strict chronology.
    for index, row in enumerate(reversed(rows)):
        if not isinstance(row, list) or len(row) < 7:
            raise BybitKlineError(f"row {index} is malformed")
        raw_open_time, raw_open, raw_high, raw_low, raw_close, raw_volume, raw_turnover = row[:7]
        try:
            open_time = int(raw_open_time)
        except (TypeError, ValueError) as exc:
            raise BybitKlineError(f"row {index} open time is malformed") from exc
        if open_time % interval_ms != 0:
            raise BybitKlineError(f"row {index} open time is off the {interval} grid")
        close_time = open_time + interval_ms - 1
        if close_time >= now_ms:
            raise BybitKlineError(f"row {index} is not a closed historical candle")
        if open_time < start_time_ms or open_time > end_time_ms:
            raise BybitKlineError(f"row {index} is outside requested bounds")
        if open_time in seen:
            raise BybitKlineError(f"duplicate candle open time: {open_time}")

        open_price = _decimal(raw_open, "open")
        high_price = _decimal(raw_high, "high")
        low_price = _decimal(raw_low, "low")
        close_price = _decimal(raw_close, "close")
        volume = _decimal(raw_volume, "volume")
        turnover = _decimal(raw_turnover, "turnover")
        if min(open_price, high_price, low_price, close_price) <= 0:
            raise BybitKlineError(f"row {index} prices must be positive")
        if volume < 0 or turnover < 0:
            raise BybitKlineError(f"row {index} volume/turnover cannot be negative")
        if high_price < max(open_price, close_price, low_price):
            raise BybitKlineError(f"row {index} high violates OHLC bounds")
        if low_price > min(open_price, close_price, high_price):
            raise BybitKlineError(f"row {index} low violates OHLC bounds")

        normalized.append({
            "source": "Bybit",
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
            "turnover": str(turnover),
            "closed": True,
        })
        seen.add(open_time)

    if require_complete_window:
        expected = _expected_open_times(start_time_ms, end_time_ms, interval_ms)
        actual = [row["open_time_ms"] for row in normalized]
        if actual != expected:
            raise BybitKlineError("Bybit kline response is incomplete or substituted for requested window")
    return normalized


def fetch_closed_klines(
    symbol: str,
    interval: str,
    *,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int = 1000,
    timeout_seconds: float = 30.0,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    normalized_symbol = _normalize_symbol(symbol)
    if interval not in SUPPORTED_INTERVALS:
        raise BybitKlineError("unsupported Bybit interval")
    if not 1 <= limit <= MAX_LIMIT:
        raise BybitKlineError(f"limit must be between 1 and {MAX_LIMIT}")
    if end_time_ms < start_time_ms:
        raise BybitKlineError("end_time_ms cannot be before start_time_ms")

    interval_ms = INTERVAL_MS[interval]
    expected = _expected_open_times(start_time_ms, end_time_ms, interval_ms)
    if not expected:
        raise BybitKlineError("requested window contains no interval-grid candle")
    if len(expected) > limit:
        raise BybitKlineError("requested window exceeds one deterministic Bybit page")
    if expected[-1] + interval_ms - 1 >= now_ms:
        raise BybitKlineError("requested window includes an open/incomplete candle")

    client = session or requests.Session()
    params = {
        "category": "spot",
        "symbol": normalized_symbol,
        "interval": interval,
        "start": start_time_ms,
        "end": end_time_ms,
        "limit": limit,
    }
    response = None
    status_codes: list[int] = []
    for base_url in BASE_URLS:
        candidate = client.get(
            f"{base_url}{KLINES_PATH}",
            params=params,
            timeout=timeout_seconds,
            allow_redirects=False,
            headers={"Accept": "application/json", "User-Agent": "nexus-research/1.0"},
        )
        status_codes.append(int(candidate.status_code))
        if candidate.status_code == 200:
            response = candidate
            break
    if response is None:
        evidence = ",".join(str(code) for code in status_codes)
        raise BybitKlineError(
            f"all official Bybit mainnet endpoints rejected the kline request: {evidence}"
        )
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise BybitKlineError("Bybit kline response exceeds size limit")
    try:
        payload = response.json()
    except ValueError as exc:
        raise BybitKlineError("Bybit kline response is not valid JSON") from exc
    return normalize_closed_klines(
        payload,
        symbol=normalized_symbol,
        interval=interval,
        now_ms=now_ms,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        require_complete_window=True,
    )
