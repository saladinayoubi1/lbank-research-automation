from __future__ import annotations

import json
from typing import Any

from bybit_public_klines import BybitKlineError, INTERVAL_MS, fetch_closed_klines
from phase6_research_pipeline import (
    bind_bybit_closed_dataset,
    fetch_bind_bybit_dataset as _fetch_bind_direct,
)

# This fallback is intentionally narrow. It never changes exchange, market,
# category or interval semantics. It only retries the exact Bybit Spot 4h
# contract as four smaller 60-candle windows when the one-page request reaches
# the existing all-approved-host terminal failure. Classified access, region,
# compliance and rate-limit failures remain fail-fast in bybit_public_klines.
_FALLBACK_INTERVAL = "240"
_CHUNK_CANDLES = 60
_MAX_FALLBACK_CANDLES = 240
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


def _eligible_terminal_failure(exc: BybitKlineError, interval: str) -> bool:
    return interval == _FALLBACK_INTERVAL and str(exc).startswith(_TERMINAL_PREFIX)


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
    count = len(expected)
    if count <= _CHUNK_CANDLES:
        raise BybitKlineError("same-interval chunk fallback would not reduce request width")
    if count > _MAX_FALLBACK_CANDLES or count > limit:
        raise BybitKlineError("same-interval chunk fallback exceeds bounded 4h history surface")

    step_ms = INTERVAL_MS[_FALLBACK_INTERVAL]
    candles: list[dict[str, Any]] = []
    chunk_count = 0
    for offset in range(0, count, _CHUNK_CANDLES):
        chunk_len = min(_CHUNK_CANDLES, count - offset)
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
                "candle_count": count,
                "chunk_candles": _CHUNK_CANDLES,
                "chunk_count": chunk_count,
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
    """Fetch canonical Bybit data with one narrow same-interval 4h fallback.

    Direct acquisition remains authoritative. Only the existing terminal failure
    across approved Bybit Mainnet hosts can enter the fallback, and the fallback
    still requests ``category=spot`` and ``interval=240`` from the same approved
    collector. No lower-timeframe aggregation or source substitution is allowed.
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
        if not _eligible_terminal_failure(exc, interval):
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
