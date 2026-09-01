from __future__ import annotations

import json
from typing import Any

from bybit_public_klines import BybitKlineError, INTERVAL_MS, fetch_closed_klines
from phase6_research_pipeline import (
    bind_bybit_closed_dataset,
    fetch_bind_bybit_dataset as _fetch_bind_direct,
)

# This fallback is intentionally bound to the one demonstrated physical blocker:
# ETH/USDT Spot, interval=240, the current 240-candle history window, and an
# all-approved-host terminal made exclusively of unclassified HTTP 403 results.
# It never changes exchange, market, category or interval semantics. Classified
# access/region/compliance/rate-limit failures and transport failures remain
# fail-closed under the original collector behavior.
_FALLBACK_CANONICAL_SYMBOL = "ETH/USDT"
_FALLBACK_SOURCE_SYMBOL = "ETHUSDT"
_FALLBACK_INTERVAL = "240"
_FALLBACK_CANDLES = 240
_CHUNK_CANDLES = 60
_TERMINAL_PREFIX = (
    "all approved Bybit Mainnet endpoints were unavailable or geographically rejected"
)


def _expected_opens(start_time_ms: int, end_time_ms: int) -> list[int]:
    step_ms = INTERVAL_MS[_FALLBACK_INTERVAL]
    if start_time_ms % step_ms != 0 or end_time_ms % step_ms != 0:
        raise BybitKlineError("chunk fallback window is off the 4h UTC grid")
    if end_time_ms < start_time_ms:
        raise BybitKlineError("chunk fallback end precedes start")
    return list(range(start_time_ms, end_time_ms + 1, step_ms))


def _all_rejections_unclassified_403(exc: BybitKlineError) -> bool:
    message = str(exc)
    prefix = _TERMINAL_PREFIX + ": "
    if not message.startswith(prefix):
        return False
    rejections = [item for item in message[len(prefix):].split(",") if item]
    return bool(rejections) and all(":http403:unclassified" in item for item in rejections)


def _eligible_terminal_failure(
    exc: BybitKlineError,
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    limit: int,
) -> bool:
    return bool(
        canonical_symbol == _FALLBACK_CANONICAL_SYMBOL
        and source_symbol == _FALLBACK_SOURCE_SYMBOL
        and interval == _FALLBACK_INTERVAL
        and limit == _FALLBACK_CANDLES
        and _all_rejections_unclassified_403(exc)
    )


def _fetch_same_interval_chunks(
    *,
    canonical_symbol: str,
    source_symbol: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    expected = _expected_opens(start_time_ms, end_time_ms)
    if len(expected) != _FALLBACK_CANDLES or limit != _FALLBACK_CANDLES:
        raise BybitKlineError("same-interval chunk fallback requires exact current 240-candle surface")

    step_ms = INTERVAL_MS[_FALLBACK_INTERVAL]
    candles: list[dict[str, Any]] = []
    chunk_count = 0
    for offset in range(0, _FALLBACK_CANDLES, _CHUNK_CANDLES):
        chunk_len = min(_CHUNK_CANDLES, _FALLBACK_CANDLES - offset)
        chunk_start = start_time_ms + offset * step_ms
        chunk_end = chunk_start + (chunk_len - 1) * step_ms
        rows = fetch_closed_klines(
            source_symbol,
            _FALLBACK_INTERVAL,
            now_ms=now_ms,
            start_time_ms=chunk_start,
            end_time_ms=chunk_end,
            limit=chunk_len,
            timeout_seconds=timeout_seconds,
        )
        if len(rows) != chunk_len:
            raise BybitKlineError("same-interval chunk response is incomplete")
        candles.extend(dict(row) for row in rows)
        chunk_count += 1

    actual = [row.get("open_time_ms") for row in candles]
    if actual != expected:
        raise BybitKlineError("same-interval chunk stitch is incomplete or off-grid")
    if any(
        row.get("source") != "Bybit"
        or row.get("market_type") != "spot"
        or row.get("symbol") != source_symbol
        or row.get("interval") != _FALLBACK_INTERVAL
        or row.get("closed") is not True
        for row in candles
    ):
        raise BybitKlineError("same-interval chunk stitch changed canonical Bybit semantics")

    print(
        "bybit_same_interval_chunk_fallback="
        + json.dumps(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": source_symbol,
                "interval": _FALLBACK_INTERVAL,
                "candle_count": len(candles),
                "chunk_candles": _CHUNK_CANDLES,
                "chunk_count": chunk_count,
                "trigger": "all_approved_hosts_unclassified_http403",
                "semantic_substitution": False,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
    )
    return bind_bybit_closed_dataset(
        candles,
        canonical_symbol=canonical_symbol,
        source_symbol=source_symbol,
        interval=_FALLBACK_INTERVAL,
    )


def fetch_bind_bybit_dataset(
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int = 1000,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    """Fetch canonical Bybit data with one narrow same-interval ETH 4h fallback.

    Direct acquisition remains authoritative. Only the demonstrated all-approved-
    host unclassified HTTP 403 failure on the exact current ETH Spot 4h surface
    can enter the fallback. The fallback still requests ``category=spot`` and
    ``interval=240`` from the same approved collector. No lower-timeframe
    aggregation or source substitution is allowed.
    """
    try:
        return _fetch_bind_direct(
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval=interval,
            now_ms=now_ms,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
    except BybitKlineError as exc:
        if not _eligible_terminal_failure(
            exc,
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval=interval,
            limit=limit,
        ):
            raise
        return _fetch_same_interval_chunks(
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            now_ms=now_ms,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
