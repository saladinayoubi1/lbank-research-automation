"""Read-only diagnostic for the *actual* mapped primary public spot feed.

The canonical registry describes compatibility, not availability. This probe
never writes a dataset, changes exchange provenance, or makes data tradeable.
Only an explicit authenticated Data Core UI action initiates the HTTP request.
"""
from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CONTRACT = "nexus.product-market-probe.v1"
TIMEFRAMES = {"15m": ("15", 900_000), "1h": ("60", 3_600_000), "4h": ("240", 14_400_000)}
MAX_RESPONSE = 96_000


class MarketProbeInputError(ValueError):
    """Unsupported pair/timeframe; never interpolate arbitrary URLs."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _download_public(url: str, timeout: float) -> bytes:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "NEXUS-DataDiagnostic/1"})
    with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
        if response.getcode() != 200:
            raise OSError("unexpected public market HTTP status")
        data = response.read(MAX_RESPONSE + 1)
        if len(data) > MAX_RESPONSE:
            raise ValueError("public payload exceeds size cap")
        return data


def _utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _price(value: Any, *, allow_zero: bool = False) -> Decimal:
    if not isinstance(value, str) or len(value) > 50:
        raise ValueError("market numeric field must be a bounded string")
    try:
        decimal = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid market decimal") from exc
    if not decimal.is_finite() or (decimal < 0 if allow_zero else decimal <= 0):
        raise ValueError("non-positive or non-finite market decimal")
    return decimal


def probe_primary_spot(
    *,
    symbol: str,
    timeframe: str,
    registry: Mapping[str, Any],
    fetcher: Callable[[str, float], bytes] = _download_public,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """One bounded, unmixed, public Bybit probe; not an execution price source."""
    if not isinstance(symbol, str) or not isinstance(timeframe, str) or timeframe not in TIMEFRAMES:
        raise MarketProbeInputError("unsupported timeframe or symbol")
    interval, step = TIMEFRAMES[timeframe]
    matching = [
        m for m in registry.get("mappings", [])
        if m.get("market_category") == "spot"
        and m.get("canonical_symbol", "").replace("/", "") == symbol
        and m.get("timeframe") == timeframe
        and m.get("finality") == "closed_only"
        and any(
            s.get("exchange") == "Bybit" and s.get("role") == "primary"
            and s.get("symbol") == symbol and s.get("category") == "spot"
            and s.get("status") == "compatible"
            for s in m.get("sources", [])
        )
    ]
    if len(matching) != 1:
        raise MarketProbeInputError("symbol/timeframe lacks one validated primary mapping")
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if type(now_ms) is not int or now_ms <= step:
        raise MarketProbeInputError("invalid diagnostic clock")
    result: dict[str, Any] = {
        "contract_version": CONTRACT, "paper_only": True, "read_only": True,
        "execution_eligible": False, "dataset_written": False,
        "source": "Bybit", "market_category": "spot", "symbol": symbol,
        "timeframe": timeframe, "source_semantics": "mapped_primary_public_spot_only",
        "checked_at_utc": _utc(now_ms), "status": "unverified",
        "reason_code": "not_checked", "http_status": None,
        "last_closed_open_utc": None, "last_closed_at_utc": None,
        "last_close_price": None, "closed_bars_verified": 0, "lag_bars": None,
    }
    url = (
        "https://api.bybit.com/v5/market/kline?category=spot"
        f"&symbol={symbol}&interval={interval}&limit=12"
    )
    try:
        raw = fetcher(url, 6.0)
    except HTTPError as exc:
        result.update(
            status="unavailable", http_status=exc.code,
            reason_code={403: "public_http_403_access_denied", 429: "public_http_429_rate_limited"}.get(
                exc.code, "public_http_failure"
            ),
        )
        return result
    except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
        result.update(status="unavailable", reason_code="public_transport_unavailable")
        return result
    except ValueError:
        result.update(status="integrity_failed", reason_code="public_payload_integrity_failure")
        return result

    try:
        if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
            raise ValueError("unbounded or invalid response bytes")
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict) or data.get("retCode") != 0:
            raise ValueError("invalid Bybit public response")
        body = data.get("result")
        if not isinstance(body, dict) or body.get("category") != "spot" or body.get("symbol") != symbol:
            raise ValueError("source response category/symbol mismatch")
        rows = body.get("list")
        if not isinstance(rows, list) or not 3 <= len(rows) <= 12:
            raise ValueError("insufficient or unbounded public rows")
        descending: list[int] = []
        closed: list[tuple[int, Decimal]] = []
        for row in rows:
            if not isinstance(row, list) or len(row) < 7 or not isinstance(row[0], str):
                raise ValueError("malformed OHLCV row")
            start = int(row[0])
            if start <= 0 or start % step or start > now_ms + step:
                raise ValueError("unaligned or future candle")
            descending.append(start)
            if start + step > now_ms:
                continue  # Bybit newest REST candle can still be updating.
            op, hi, lo, cl = (_price(row[n]) for n in (1, 2, 3, 4))
            volume = _price(row[5], allow_zero=True)
            turnover = _price(row[6], allow_zero=True)
            if hi < max(op, cl) or lo > min(op, cl) or hi < lo or volume < 0 or turnover < 0:
                raise ValueError("invalid closed OHLCV range")
            closed.append((start, cl))
        if any(a <= b for a, b in zip(descending, descending[1:])):
            raise ValueError("duplicate or misordered market candles")
        if len(closed) < 3:
            result.update(status="unavailable", reason_code="insufficient_closed_candles")
            return result
        recent = closed[:5]  # reverse chronological; newest active candle was removed.
        if any(a[0] - b[0] != step for a, b in zip(recent, recent[1:])):
            result.update(status="integrity_failed", reason_code="recent_closed_candle_gap")
            return result
        last_open, last_close_price = closed[0]
        last_closed_at = last_open + step
        boundary = (now_ms // step) * step
        if last_closed_at > boundary:
            raise ValueError("last completed bar is in the future")
        lag = (boundary - last_closed_at) // step
        result.update(
            last_closed_open_utc=_utc(last_open),
            last_closed_at_utc=_utc(last_closed_at),
            closed_bars_verified=len(recent),
            lag_bars=lag,
        )
        if lag:
            result.update(status="stale", reason_code="latest_closed_bar_missing")
        else:
            result.update(
                status="verified_closed_candles", reason_code="source_probe_passed",
                last_close_price=str(last_close_price),
            )
        return result
    except (ValueError, TypeError, KeyError, OverflowError, UnicodeDecodeError, json.JSONDecodeError):
        result.update(status="integrity_failed", reason_code="public_payload_integrity_failure")
        return result


PAPER_MARK_CONTRACT = "nexus.product-paper-market-display.v1"
MAX_PAPER_MARK_SYMBOLS = 8
MAX_PAPER_MARK_AGE_SECONDS = 120


def probe_public_linear_marks(
    *,
    symbols: list[str] | tuple[str, ...],
    fetcher: Callable[[str, float], bytes] = _download_public,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Fresh Bybit public mark prices for Demo display only.

    The result is never eligible for signal generation, deterministic risk,
    Paper execution, registry promotion or Live trading. All requested symbols
    must validate as fresh or the full mark overlay fails closed.
    """
    if not isinstance(symbols, (list, tuple)):
        raise MarketProbeInputError("paper mark symbols must be a bounded sequence")
    unique: list[str] = []
    for symbol in symbols:
        if (
            not isinstance(symbol, str)
            or not 4 <= len(symbol) <= 20
            or not symbol.isascii()
            or not symbol.isalnum()
            or symbol.upper() != symbol
        ):
            raise MarketProbeInputError("invalid paper mark symbol")
        if symbol not in unique:
            unique.append(symbol)
    if len(unique) > MAX_PAPER_MARK_SYMBOLS:
        raise MarketProbeInputError("too many paper mark symbols")
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    if type(now_ms) is not int or now_ms <= 0:
        raise MarketProbeInputError("invalid paper mark clock")

    result: dict[str, Any] = {
        "contract_version": PAPER_MARK_CONTRACT,
        "paper_only": True,
        "read_only": True,
        "display_only": True,
        "execution_eligible": False,
        "risk_eligible": False,
        "dataset_written": False,
        "live_trading_authority": False,
        "source": "Bybit",
        "market_category": "linear",
        "checked_at_utc": _utc(now_ms),
        "status": "not_needed_flat" if not unique else "unverified",
        "reason_code": "no_open_positions" if not unique else "not_checked",
        "http_status": None,
        "marks": {},
    }
    if not unique:
        return result

    marks: dict[str, Any] = {}
    for symbol in unique:
        url = (
            "https://api.bybit.com/v5/market/tickers"
            f"?category=linear&symbol={symbol}"
        )
        try:
            raw = fetcher(url, 4.0)
        except HTTPError as exc:
            result.update(
                status="unavailable",
                http_status=exc.code,
                reason_code={
                    403: "public_http_403_access_denied",
                    429: "public_http_429_rate_limited",
                }.get(exc.code, "public_http_failure"),
                marks={},
            )
            return result
        except (URLError, TimeoutError, socket.timeout, ConnectionError, OSError):
            result.update(
                status="unavailable",
                reason_code="public_transport_unavailable",
                marks={},
            )
            return result
        except ValueError:
            result.update(
                status="integrity_failed",
                reason_code="public_payload_integrity_failure",
                marks={},
            )
            return result

        try:
            if not isinstance(raw, bytes) or len(raw) > MAX_RESPONSE:
                raise ValueError("unbounded or invalid response bytes")
            data = json.loads(raw.decode("utf-8"))
            server_ms = data.get("time")
            if (
                not isinstance(data, dict)
                or data.get("retCode") != 0
                or isinstance(server_ms, bool)
                or not isinstance(server_ms, int)
                or server_ms <= 0
            ):
                raise ValueError("invalid Bybit public ticker response")
            age_seconds = (now_ms - server_ms) / 1000.0
            if not -10 <= age_seconds <= MAX_PAPER_MARK_AGE_SECONDS:
                raise ValueError("stale public ticker timestamp")
            body = data.get("result")
            rows = body.get("list") if isinstance(body, dict) else None
            if (
                not isinstance(body, dict)
                or body.get("category") != "linear"
                or not isinstance(rows, list)
                or len(rows) != 1
                or not isinstance(rows[0], dict)
                or rows[0].get("symbol") != symbol
            ):
                raise ValueError("ticker category/symbol mismatch")
            mark = _price(rows[0].get("markPrice"))
            marks[symbol] = {
                "symbol": symbol,
                "mark_price": str(mark),
                "mark_time_utc": _utc(server_ms),
                "age_seconds": max(age_seconds, 0.0),
            }
        except (ValueError, TypeError, KeyError, OverflowError, UnicodeDecodeError, json.JSONDecodeError):
            result.update(
                status="integrity_failed",
                reason_code="public_payload_integrity_failure",
                marks={},
            )
            return result

    result.update(
        status="fresh",
        reason_code="public_mark_probe_passed",
        marks=marks,
    )
    return result
