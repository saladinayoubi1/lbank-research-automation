from __future__ import annotations

import json
import time
from typing import Any

import requests

from bybit_public_klines import (
    BybitKlineError,
    INTERVAL_MS,
    KLINES_PATH,
    MAX_RESPONSE_BYTES,
    UNCLASSIFIED_403_RETRY_DELAYS_SECONDS,
    _active_mainnet_base_urls,
    _classify_403,
    _emit_403_diagnostic,
    _new_cdn_request_id,
    fetch_closed_klines,
    normalize_closed_klines,
)
from phase6_research_pipeline import (
    bind_bybit_closed_dataset,
    fetch_bind_bybit_dataset as _fetch_bind_direct,
)

# The original chunk fallback is intentionally retained for the demonstrated
# ETH/USDT Spot 4h request-width blocker. Physical run 33522480622 then proved
# that unclassified HTTP 403 can also occur across symbols/intervals and even on
# the smaller 4h chunks. The second-stage fallback below therefore changes only
# the request shape on the same official Bybit Spot kline endpoint: start+end+
# limit -> end+limit, which Bybit documents as an optional-parameter form.
# Returned candles still have to match the exact original 240-candle UTC grid.
# No endpoint, exchange, market, symbol, interval, credential or candle semantics
# are substituted. Classified 403s, mixed transport failures and malformed or
# incomplete responses remain fail-closed.
_FALLBACK_CANONICAL_SYMBOL = "ETH/USDT"
_FALLBACK_SOURCE_SYMBOL = "ETHUSDT"
_FALLBACK_INTERVAL = "240"
_FALLBACK_CANDLES = 240
_CHUNK_CANDLES = 60
_TERMINAL_PREFIX = (
    "all approved Bybit Mainnet endpoints were unavailable or geographically rejected"
)
_CANONICAL_SURFACE = {
    ("BTC/USDT", "BTCUSDT"),
    ("ETH/USDT", "ETHUSDT"),
}
_REQUEST_SHAPE_INTERVALS = frozenset({"15", "60", "240"})
_FAIL_FAST_403 = frozenset(
    {
        "access_too_frequent",
        "api_rate_limited",
        "ip_banned",
        "region_restricted",
        "unmatched_ip",
        "compliance_restricted",
    }
)


def _expected_opens(start_time_ms: int, end_time_ms: int) -> list[int]:
    step_ms = INTERVAL_MS[_FALLBACK_INTERVAL]
    if start_time_ms % step_ms != 0 or end_time_ms % step_ms != 0:
        raise BybitKlineError("chunk fallback window is off the 4h UTC grid")
    if end_time_ms < start_time_ms:
        raise BybitKlineError("chunk fallback end precedes start")
    return list(range(start_time_ms, end_time_ms + 1, step_ms))


def _expected_surface_opens(
    *, interval: str, start_time_ms: int, end_time_ms: int, limit: int
) -> list[int]:
    if interval not in _REQUEST_SHAPE_INTERVALS:
        raise BybitKlineError("end-anchored fallback interval is outside the canonical matrix")
    step_ms = INTERVAL_MS[interval]
    if start_time_ms % step_ms != 0 or end_time_ms % step_ms != 0:
        raise BybitKlineError("end-anchored fallback window is off the interval UTC grid")
    if end_time_ms < start_time_ms:
        raise BybitKlineError("end-anchored fallback end precedes start")
    expected = list(range(start_time_ms, end_time_ms + 1, step_ms))
    if limit != _FALLBACK_CANDLES or len(expected) != _FALLBACK_CANDLES:
        raise BybitKlineError("end-anchored fallback requires exact current 240-candle surface")
    return expected


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


def _eligible_end_anchored_failure(
    exc: BybitKlineError,
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    limit: int,
) -> bool:
    return bool(
        (canonical_symbol, source_symbol) in _CANONICAL_SURFACE
        and interval in _REQUEST_SHAPE_INTERVALS
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


def _request_end_anchored_host(
    client: requests.Session,
    base_url: str,
    *,
    symbol: str,
    interval: str,
    end_time_ms: int,
    limit: int,
    timeout_seconds: float,
):
    # base_url comes exclusively from _active_mainnet_base_urls(); callers cannot
    # inject a host. The request intentionally omits only the optional `start`.
    cdn_request_id = _new_cdn_request_id()
    response = client.get(
        f"{base_url}{KLINES_PATH}",
        params={
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "end": end_time_ms,
            "limit": limit,
        },
        timeout=timeout_seconds,
        allow_redirects=False,
        headers={
            "Accept": "application/json",
            "User-Agent": "nexus-research/1.0",
            "cdn-request-id": cdn_request_id,
        },
    )
    return response, cdn_request_id


def _fetch_end_anchored_closed_klines(
    *,
    source_symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int,
    timeout_seconds: float,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    expected = _expected_surface_opens(
        interval=interval,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        limit=limit,
    )
    if expected[-1] + INTERVAL_MS[interval] - 1 >= now_ms:
        raise BybitKlineError("end-anchored fallback includes an open/incomplete candle")

    region, base_urls = _active_mainnet_base_urls()
    if region != "GLOBAL":
        print(
            "bybit_public_endpoint_selection="
            + json.dumps(
                {"region": region, "base_urls": list(base_urls)},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
        )

    client = session or requests.Session()
    rejected_hosts: list[str] = []
    retry_rounds = len(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS) + 1
    for round_index in range(retry_rounds):
        round_rejections: list[str] = []
        unclassified_403_count = 0
        for base_url in base_urls:
            try:
                response, cdn_request_id = _request_end_anchored_host(
                    client,
                    base_url,
                    symbol=source_symbol,
                    interval=interval,
                    end_time_ms=end_time_ms,
                    limit=limit,
                    timeout_seconds=timeout_seconds,
                )
            except requests.RequestException as exc:
                round_rejections.append(f"{base_url}:transport:{type(exc).__name__}")
                continue

            if response.status_code == 403:
                reason, ret_code, ret_code_category, ret_msg_category = _classify_403(response)
                _emit_403_diagnostic(
                    response,
                    base_url=base_url,
                    symbol=source_symbol,
                    interval=interval,
                    cdn_request_id=cdn_request_id,
                    reason=reason,
                    ret_code=ret_code,
                    ret_code_category=ret_code_category,
                    ret_msg_category=ret_msg_category,
                )
                round_rejections.append(f"{base_url}:http403:{reason}")
                if reason in _FAIL_FAST_403:
                    raise BybitKlineError(
                        f"Bybit Mainnet access is blocked (HTTP 403 {reason}); repeated requests suppressed"
                    )
                if reason == "unclassified":
                    unclassified_403_count += 1
                continue
            if response.status_code != 200:
                raise BybitKlineError(
                    f"Bybit end-anchored kline request failed with HTTP {response.status_code}"
                )
            if len(response.content) > MAX_RESPONSE_BYTES:
                raise BybitKlineError("Bybit end-anchored kline response exceeds size limit")
            try:
                payload = response.json()
            except ValueError as exc:
                raise BybitKlineError("Bybit end-anchored kline response is not valid JSON") from exc
            rows = normalize_closed_klines(
                payload,
                symbol=source_symbol,
                interval=interval,
                now_ms=now_ms,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                require_complete_window=True,
            )
            if [row["open_time_ms"] for row in rows] != expected:
                raise BybitKlineError("end-anchored response did not reproduce the exact requested surface")
            return rows

        rejected_hosts.extend(round_rejections)
        all_hosts_unclassified_403 = (
            len(round_rejections) == len(base_urls)
            and unclassified_403_count == len(base_urls)
        )
        if (
            all_hosts_unclassified_403
            and round_index < len(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS)
        ):
            time.sleep(UNCLASSIFIED_403_RETRY_DELAYS_SECONDS[round_index])
            continue
        break

    detail = ",".join(rejected_hosts)
    raise BybitKlineError(
        _TERMINAL_PREFIX + (f": {detail}" if detail else "")
    )


def _fetch_end_anchored_dataset(
    *,
    canonical_symbol: str,
    source_symbol: str,
    interval: str,
    now_ms: int,
    start_time_ms: int,
    end_time_ms: int,
    limit: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    candles = _fetch_end_anchored_closed_klines(
        source_symbol=source_symbol,
        interval=interval,
        now_ms=now_ms,
        start_time_ms=start_time_ms,
        end_time_ms=end_time_ms,
        limit=limit,
        timeout_seconds=timeout_seconds,
    )
    print(
        "bybit_same_semantics_request_shape_fallback="
        + json.dumps(
            {
                "source": "Bybit",
                "market_type": "spot",
                "symbol": source_symbol,
                "interval": interval,
                "candle_count": len(candles),
                "request_shape": "end_plus_limit",
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
        interval=interval,
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
    """Fetch the six-cell canonical Bybit surface with bounded REST fallbacks.

    Direct start+end acquisition stays authoritative. ETH Spot 4h retains its
    physically motivated same-interval chunk attempt. If that attempt, or any
    other approved BTC/ETH 15m/1h/4h 240-candle direct request, ends only in
    unclassified 403s across the approved official hosts, one second request
    shape is allowed: same endpoint/category/symbol/interval with `end+limit`
    and no optional `start`. Exact candle timestamps are revalidated before the
    canonical binder can accept the result.
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
        if _eligible_terminal_failure(
            exc,
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval=interval,
            limit=limit,
        ):
            try:
                return _fetch_same_interval_chunks(
                    canonical_symbol=canonical_symbol,
                    source_symbol=source_symbol,
                    now_ms=now_ms,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    limit=limit,
                    timeout_seconds=timeout_seconds,
                )
            except BybitKlineError as chunk_exc:
                if not _eligible_end_anchored_failure(
                    chunk_exc,
                    canonical_symbol=canonical_symbol,
                    source_symbol=source_symbol,
                    interval=interval,
                    limit=limit,
                ):
                    raise
                return _fetch_end_anchored_dataset(
                    canonical_symbol=canonical_symbol,
                    source_symbol=source_symbol,
                    interval=interval,
                    now_ms=now_ms,
                    start_time_ms=start_time_ms,
                    end_time_ms=end_time_ms,
                    limit=limit,
                    timeout_seconds=timeout_seconds,
                )

        if not _eligible_end_anchored_failure(
            exc,
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval=interval,
            limit=limit,
        ):
            raise
        return _fetch_end_anchored_dataset(
            canonical_symbol=canonical_symbol,
            source_symbol=source_symbol,
            interval=interval,
            now_ms=now_ms,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            limit=limit,
            timeout_seconds=timeout_seconds,
        )
