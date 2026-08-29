from __future__ import annotations

import hashlib
import json
import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

import requests

# Bybit documents both hosts as equivalent public Mainnet REST endpoints. The
# ordered pair is intentionally fixed and bounded. HTTP 403 is ambiguous in the
# provider contract (IP frequency, regional restriction, or malformed request),
# so the collector classifies only explicit public-response evidence and never
# converts a 403 into successful market data. No third-party proxy, exchange
# substitution, private credential or testnet endpoint is permitted.
OFFICIAL_MAINNET_BASE_URLS = (
    "https://api.bybit.com",
    "https://api.bytick.com",
)
BASE_URL = OFFICIAL_MAINNET_BASE_URLS[0]
KLINES_PATH = "/v5/market/kline"
INTERVAL_MS = {"15": 15 * 60 * 1000, "60": 60 * 60 * 1000, "240": 4 * 60 * 60 * 1000}
SUPPORTED_INTERVALS = set(INTERVAL_MS)
MAX_LIMIT = 1000
MAX_RESPONSE_BYTES = 2_000_000
_DIAGNOSTIC_BODY_LIMIT = 4096
_CONTENT_TYPE_RE = re.compile(r"^[a-z0-9.+/-]{1,80}$")


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


def _new_cdn_request_id() -> str:
    return f"nexus-{uuid.uuid4().hex}"


def _safe_content_type(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    value = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
    return value if _CONTENT_TYPE_RE.fullmatch(value) else "unknown"


def _ret_code_category(ret_code: int | None) -> str:
    # Current Bybit V5 error-code semantics. Keep this intentionally small and
    # diagnostic-only; an error code can never authorize market-data acceptance.
    return {
        10006: "api_rate_limited",
        10009: "region_restricted",
        10010: "unmatched_ip",
        10024: "compliance_restricted",
    }.get(ret_code, "unknown" if ret_code is not None else "missing")


def _ret_msg_category(value: Any) -> str:
    if not isinstance(value, str):
        return "missing"
    normalized = " ".join(value.strip().lower().split())
    if not normalized:
        return "empty"
    if "access too frequent" in normalized or "too many visits" in normalized:
        return "access_too_frequent"
    if "ip" in normalized and ("banned" in normalized or "blocked" in normalized):
        return "ip_banned"
    if "service restricted" in normalized or ("restricted" in normalized and "region" in normalized):
        return "region_restricted"
    if "compliance" in normalized and ("trigger" in normalized or "restrict" in normalized):
        return "compliance_restricted"
    if "unmatched ip" in normalized:
        return "unmatched_ip"
    if "forbidden" in normalized or "access denied" in normalized:
        return "access_forbidden"
    return "other"


def _json_403_metadata(response: Any) -> tuple[int | None, str, str]:
    if _safe_content_type(response) != "application/json":
        return None, "missing", "not_json"
    try:
        payload = response.json()
    except (TypeError, ValueError):
        return None, "missing", "invalid_json"
    if not isinstance(payload, dict):
        return None, "missing", "non_object_json"
    raw_code = payload.get("retCode")
    ret_code = raw_code if isinstance(raw_code, int) and not isinstance(raw_code, bool) else None
    return ret_code, _ret_code_category(ret_code), _ret_msg_category(payload.get("retMsg"))


def _classify_403(response: Any) -> tuple[str, int | None, str, str]:
    ret_code, ret_code_category, ret_msg_category = _json_403_metadata(response)
    if ret_code_category in {
        "api_rate_limited",
        "region_restricted",
        "unmatched_ip",
        "compliance_restricted",
    }:
        return ret_code_category, ret_code, ret_code_category, ret_msg_category
    if ret_msg_category in {
        "access_too_frequent",
        "ip_banned",
        "region_restricted",
        "unmatched_ip",
        "compliance_restricted",
        "access_forbidden",
    }:
        return ret_msg_category, ret_code, ret_code_category, ret_msg_category

    content = bytes(getattr(response, "content", b""))[:_DIAGNOSTIC_BODY_LIMIT].lower()
    if b"access too frequent" in content:
        return "access_too_frequent", ret_code, ret_code_category, ret_msg_category
    if b"service restricted" in content or (b"restricted" in content and b"region" in content):
        return "region_restricted", ret_code, ret_code_category, ret_msg_category
    return "unclassified", ret_code, ret_code_category, ret_msg_category


def _edge_class(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    server = str(headers.get("Server", "")).lower()
    if "cloudflare" in server or headers.get("CF-Ray"):
        return "cloudflare"
    if "cloudfront" in server or headers.get("X-Amz-Cf-Id") or headers.get("X-Cache"):
        return "cloudfront"
    if "akamai" in server:
        return "akamai"
    return "unknown"


def _emit_403_diagnostic(
    response: Any,
    *,
    base_url: str,
    symbol: str,
    interval: str,
    cdn_request_id: str,
    reason: str,
    ret_code: int | None,
    ret_code_category: str,
    ret_msg_category: str,
) -> None:
    content = bytes(getattr(response, "content", b""))
    diagnostic = {
        "event": "bybit_public_http403",
        "base_url": base_url,
        "symbol": symbol,
        "interval": interval,
        "classification": reason,
        "ret_code": ret_code,
        "ret_code_category": ret_code_category,
        "ret_msg_category": ret_msg_category,
        "edge": _edge_class(response),
        "content_type": _safe_content_type(response),
        "body_bytes": len(content),
        "body_sha256": hashlib.sha256(content).hexdigest(),
        "cdn_request_id": cdn_request_id,
    }
    print("bybit_http403_diagnostic=" + json.dumps(
        diagnostic, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ))


def _request_one_official_mainnet_host(
    client: requests.Session,
    base_url: str,
    *,
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
    limit: int,
    timeout_seconds: float,
):
    if base_url not in OFFICIAL_MAINNET_BASE_URLS:
        raise BybitKlineError("unapproved Bybit Mainnet endpoint")
    cdn_request_id = _new_cdn_request_id()
    response = client.get(
        f"{base_url}{KLINES_PATH}",
        params={
            "category": "spot",
            "symbol": symbol,
            "interval": interval,
            "start": start_time_ms,
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
    rejected_hosts: list[str] = []
    for base_url in OFFICIAL_MAINNET_BASE_URLS:
        try:
            response, cdn_request_id = _request_one_official_mainnet_host(
                client,
                base_url,
                symbol=normalized_symbol,
                interval=interval,
                start_time_ms=start_time_ms,
                end_time_ms=end_time_ms,
                limit=limit,
                timeout_seconds=timeout_seconds,
            )
        except requests.RequestException as exc:
            rejected_hosts.append(f"{base_url}:transport:{type(exc).__name__}")
            continue

        if response.status_code == 403:
            reason, ret_code, ret_code_category, ret_msg_category = _classify_403(response)
            _emit_403_diagnostic(
                response,
                base_url=base_url,
                symbol=normalized_symbol,
                interval=interval,
                cdn_request_id=cdn_request_id,
                reason=reason,
                ret_code=ret_code,
                ret_code_category=ret_code_category,
                ret_msg_category=ret_msg_category,
            )
            rejected_hosts.append(f"{base_url}:http403:{reason}")
            if reason in {
                "access_too_frequent",
                "api_rate_limited",
                "ip_banned",
                "region_restricted",
                "unmatched_ip",
                "compliance_restricted",
            }:
                close = getattr(client, "close", None)
                if callable(close):
                    close()
                raise BybitKlineError(
                    f"Bybit Mainnet access is blocked (HTTP 403 {reason}); "
                    "repeated requests suppressed"
                )
            continue
        if response.status_code != 200:
            raise BybitKlineError(f"Bybit kline request failed with HTTP {response.status_code}")
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

    detail = ",".join(rejected_hosts)
    raise BybitKlineError(
        "all approved Bybit Mainnet endpoints were unavailable or geographically rejected"
        + (f": {detail}" if detail else "")
    )
