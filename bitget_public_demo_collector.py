"""Bounded public Bitget candle collection for the isolated Demo candidate.

Only official public GET endpoints are permitted.  Responses are cached immutably by
canonical URL and body digest.  This module has no account, credential, order, Paper,
Strategy promotion, or Live surface.
"""
from __future__ import annotations

from dataclasses import dataclass
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request

from bitget_isolated_demo_adapter import BitgetBar, parse_closed_bars


HOST = "api.bitget.com"
TRADE_CANDLES_PATH = "/api/v2/mix/market/history-candles"
ALLOWED_PATHS = frozenset({TRADE_CANDLES_PATH})
MAX_BODY_BYTES = 2_000_000
MAX_PAGE_SIZE = 200
MAX_PAGES = 64
TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


class BitgetCollectorError(RuntimeError):
    pass


class BitgetRequestBudgetExceeded(BitgetCollectorError):
    pass


@dataclass(frozen=True)
class PublicResponse:
    status: int
    body: bytes


Transport = Callable[[str], PublicResponse]


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def canonical_url(path: str, params: Mapping[str, Any]) -> str:
    if path not in ALLOWED_PATHS:
        raise BitgetCollectorError("DESTINATION_NOT_ALLOWED")
    query = urllib.parse.urlencode(sorted((str(key), str(value)) for key, value in params.items()))
    return f"https://{HOST}{path}?{query}"


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value) + b"\n")
    temporary.replace(path)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BitgetCollectorError("HTTP_REDIRECT_REJECTED")


def direct_transport(url: str) -> PublicResponse:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path not in ALLOWED_PATHS:
        raise BitgetCollectorError("DESTINATION_NOT_ALLOWED")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "NEXUS-bitget-demo-collector/1"},
        method="GET",
    )
    try:
        with opener.open(request, timeout=10) as response:
            body = response.read(MAX_BODY_BYTES + 1)
            return PublicResponse(int(response.status), body)
    except urllib.error.HTTPError as exc:
        return PublicResponse(int(exc.code), b"")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise BitgetCollectorError("TRANSPORT_FAILURE") from exc


class BitgetPublicReader:
    def __init__(
        self,
        cache_root: Path,
        *,
        request_budget: int = 48,
        transport: Transport = direct_transport,
        observed_at: Callable[[], str] | None = None,
    ) -> None:
        if request_budget < 1 or request_budget > 128:
            raise ValueError("request_budget outside bounded range")
        self.cache_root = Path(cache_root)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.request_budget = request_budget
        self.transport = transport
        self.observed_at = observed_at or (
            lambda: dt.datetime.now(dt.timezone.utc).isoformat()
        )
        self.requests = 0
        self.receipts: list[dict[str, Any]] = []
        self.access_denied = False

    def _cache_path(self, url: str) -> Path:
        return self.cache_root / f"{hashlib.sha256(url.encode()).hexdigest()}.json"

    def _load_cache(self, url: str, path: Path) -> dict[str, Any]:
        try:
            receipt = json.loads(path.read_bytes())
            body = receipt["body"]
            digest = hashlib.sha256(canonical_json(body)).hexdigest()
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise BitgetCollectorError("CACHE_INVALID") from exc
        if receipt.get("url") != url or receipt.get("body_sha256") != digest:
            raise BitgetCollectorError("CACHE_DIGEST_MISMATCH")
        self.receipts.append({key: value for key, value in receipt.items() if key != "body"})
        return body

    def get(self, path: str, params: Mapping[str, Any]) -> dict[str, Any]:
        if self.access_denied:
            raise BitgetCollectorError("PROVIDER_ACCESS_DENIED")
        url = canonical_url(path, params)
        cached = self._cache_path(url)
        if cached.exists():
            return self._load_cache(url, cached)

        last_status: int | None = None
        for attempt in (1, 2):
            if self.requests >= self.request_budget:
                raise BitgetRequestBudgetExceeded("REQUEST_BUDGET_CHECKPOINT")
            self.requests += 1
            response = self.transport(url)
            last_status = response.status
            if response.status in {401, 403}:
                self.access_denied = True
                raise BitgetCollectorError("PROVIDER_ACCESS_DENIED")
            if response.status in TRANSIENT_STATUS and attempt == 1:
                continue
            if response.status != 200:
                raise BitgetCollectorError(f"HTTP_{response.status}")
            if len(response.body) > MAX_BODY_BYTES:
                raise BitgetCollectorError("BODY_TOO_LARGE")
            try:
                body = json.loads(response.body)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise BitgetCollectorError("PROVIDER_JSON_INVALID") from exc
            if not isinstance(body, dict) or body.get("code") != "00000":
                raise BitgetCollectorError("PROVIDER_CODE_INVALID")
            receipt = {
                "url": url,
                "observed_at": self.observed_at(),
                "http_status": 200,
                "attempts": attempt,
                "body_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
                "body": body,
            }
            _atomic_json(cached, receipt)
            self.receipts.append({key: value for key, value in receipt.items() if key != "body"})
            return body
        raise BitgetCollectorError(f"HTTP_{last_status}")


def _rows(body: Mapping[str, Any]) -> list[list[Any]]:
    data = body.get("data")
    if not isinstance(data, list):
        raise BitgetCollectorError("PROVIDER_DATA_SCHEMA_INVALID")
    return data


def collect_trade_candle_window(
    reader: BitgetPublicReader,
    *,
    symbol: str,
    interval: str,
    interval_ms: int,
    start_ms: int,
    end_exclusive_ms: int,
) -> tuple[BitgetBar, ...]:
    """Collect one exact futures trade-candle window with bounded reverse pagination."""
    if symbol not in {"BTCUSDT", "ETHUSDT"}:
        raise BitgetCollectorError("SYMBOL_NOT_ALLOWED")
    if interval not in {"1m", "15m", "1H", "4H"}:
        raise BitgetCollectorError("INTERVAL_NOT_ALLOWED")
    if interval_ms <= 0 or start_ms < 0 or end_exclusive_ms <= start_ms:
        raise BitgetCollectorError("INVALID_WINDOW")
    expected_count = (end_exclusive_ms - start_ms) // interval_ms
    if expected_count < 1 or expected_count > MAX_PAGE_SIZE * MAX_PAGES:
        raise BitgetCollectorError("WINDOW_OUTSIDE_BOUNDED_RANGE")

    cursor = end_exclusive_ms
    collected: dict[int, list[Any]] = {}
    pages = 0
    while cursor > start_ms:
        pages += 1
        if pages > MAX_PAGES:
            raise BitgetCollectorError("PAGINATION_LIMIT_EXCEEDED")
        body = reader.get(
            TRADE_CANDLES_PATH,
            {
                "symbol": symbol,
                "productType": "USDT-FUTURES",
                "granularity": interval,
                "startTime": start_ms,
                "endTime": cursor,
                "limit": MAX_PAGE_SIZE,
            },
        )
        batch = _rows(body)
        if not batch:
            break
        timestamps: list[int] = []
        for row in batch:
            if not isinstance(row, list) or len(row) < 7:
                raise BitgetCollectorError("PROVIDER_CANDLE_SCHEMA_INVALID")
            try:
                stamp = int(str(row[0]))
            except (TypeError, ValueError) as exc:
                raise BitgetCollectorError("PROVIDER_CANDLE_TIMESTAMP_INVALID") from exc
            if str(stamp) != str(row[0]):
                raise BitgetCollectorError("PROVIDER_CANDLE_TIMESTAMP_INVALID")
            timestamps.append(stamp)
            if start_ms <= stamp < end_exclusive_ms:
                previous = collected.get(stamp)
                if previous is not None and previous != row:
                    raise BitgetCollectorError("CONFLICTING_CANDLE_DUPLICATE")
                collected[stamp] = row
        oldest = min(timestamps)
        if oldest <= start_ms:
            break
        if oldest >= cursor:
            raise BitgetCollectorError("PAGINATION_NOT_ADVANCING")
        # Bitget excludes the endTime boundary after flooring it; do not subtract 1ms.
        cursor = oldest

    return parse_closed_bars(
        list(collected.values()),
        interval_ms=interval_ms,
        start_ms=start_ms,
        end_exclusive_ms=end_exclusive_ms,
    )


def collection_manifest(
    reader: BitgetPublicReader,
    *,
    symbol: str,
    interval: str,
    interval_ms: int,
    start_ms: int,
    end_exclusive_ms: int,
    bars: tuple[BitgetBar, ...],
) -> dict[str, Any]:
    normalized = [
        [
            bar.open_time_ms,
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.base_volume),
            str(bar.quote_volume),
        ]
        for bar in bars
    ]
    return {
        "schema": "nexus.bitget-public-demo-collection.v1",
        "provider": "bitget",
        "product_type": "USDT-FUTURES",
        "scope": "isolated_demo_candidate",
        "symbol": symbol,
        "interval": interval,
        "interval_ms": interval_ms,
        "start_ms": start_ms,
        "end_exclusive_ms": end_exclusive_ms,
        "bar_count": len(bars),
        "normalized_sha256": hashlib.sha256(canonical_json(normalized)).hexdigest(),
        "http_receipts": list(reader.receipts),
        "requests_this_run": reader.requests,
        "private_credentials_used": False,
        "orders_sent": False,
        "owner_paper_mutated": False,
        "demo_replacement_authorized": False,
        "strategy_promotion_authority": False,
        "live_trading_authority": False,
    }
