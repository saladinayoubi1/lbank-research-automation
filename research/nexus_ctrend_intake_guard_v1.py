"""Pure metadata-request preflight; no network, credentials, files or trading.

An accepted request is only an allowlisted metadata request. A date range never
authorizes price/label acquisition or certifies historical listings/vintages.
The optional response check detects obvious market-data fields, not arbitrary
payload attacks, provider authenticity, response success or a complete schema.
"""
from collections.abc import Mapping
from datetime import datetime, timezone
import math
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


BYBIT = ("api.bybit.com", "/v5/market/instruments-info")
CMC = ("pro-api.coinmarketcap.com", "/public-api/v1/cryptocurrency/map")
STATUSES = ("active", "inactive", "untracked")
MIN_DATE = datetime(2021, 1, 1, tzinfo=timezone.utc)
CUTOFF = datetime(2026, 10, 19, tzinfo=timezone.utc)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?Z\Z")
_POSITIVE_INT = re.compile(r"[1-9][0-9]*\Z")
_SYMBOL = re.compile(r"[A-Z0-9]{1,64}\Z")
_MARKET_FIELDS = frozenset({
    "price", "priceusd", "lastprice", "markprice", "indexprice", "bidprice",
    "askprice", "bid1price", "ask1price", "quote", "quotes", "ohlc", "ohlcv",
    "open", "high", "low", "close", "volume", "volume24h", "turnover",
    "turnover24h", "return", "returns", "marketcap", "marketcapusd",
    "selfreportedmarketcap",
})


class IntakeRejected(ValueError):
    """The request or response is outside this metadata-only stage."""


def _authority_flags():
    return {
        "metadata_only": True, "historical_vintage_certified": False,
        "complete_universe_certified": False, "price_fetch_authorized": False,
        "label_fetch_authorized": False, "financial_fetch_authorized": False,
        "financial_backtest_authorized": False, "demo_admitted": False,
        "paper_writer_enabled": False, "live_enabled": False,
        "orders": 0, "network_requests": 0,
    }


def _date(value):
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise IntakeRejected("Coverage requires explicit UTC ISO dates with Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise IntakeRejected("Invalid coverage date") from exc


def _coverage(start, end):
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise IntakeRejected("Coverage start and exclusive end must both be supplied")
    first, last = _date(start), _date(end)
    if not MIN_DATE <= first < last <= CUTOFF:
        raise IntakeRejected("Coverage must stay within the permitted pre-freeze interval")
    return {"start": first.isoformat().replace("+00:00", "Z"),
            "end_exclusive": last.isoformat().replace("+00:00", "Z")}


def preflight(url, *, coverage_start=None, coverage_end=None, request_kind="metadata"):
    """Return a canonical allowlisted URL and explicit nonfinancial authority.

    CMC listing_status is required: the provider's omitted-parameter default is
    active only. An explicit subset is reported as such; even all three requested
    statuses do not prove a complete or historically available universe.
    """
    if request_kind != "metadata":
        raise IntakeRejected("Only metadata requests are permitted")
    if (not isinstance(url, str) or not url.startswith("https://")
            or any(ord(c) < 33 or ord(c) == 127 or c.isspace() for c in url)
            or "#" in url):
        raise IntakeRejected("Require an explicit HTTPS URL without whitespace or fragments")
    try:
        parts = urlsplit(url)
        # Exact netloc rejects credentials, ports, aliases and encoded hosts.
        endpoint = (parts.netloc, parts.path)
        if parts.scheme != "https" or endpoint not in (BYBIT, CMC):
            raise IntakeRejected("Endpoint is outside the metadata allowlist")
        pairs = parse_qsl(parts.query, keep_blank_values=True,
                          strict_parsing=True, errors="strict", max_num_fields=8)
    except (ValueError, UnicodeError) as exc:
        raise IntakeRejected("Malformed metadata URL or query") from exc
    query = {}
    for key, value in pairs:
        if key in query:
            raise IntakeRejected("Duplicate query parameter")
        query[key] = value
    coverage = _coverage(coverage_start, coverage_end)
    status_coverage = None
    if endpoint == BYBIT:
        if set(query) - {"category", "symbol"} or query.get("category") != "spot":
            raise IntakeRejected("Bybit metadata requires category=spot and no extra parameters")
        if "symbol" in query and not _SYMBOL.fullmatch(query["symbol"]):
            raise IntakeRejected("Bybit symbol must be uppercase alphanumeric")
        canonical = {"category": "spot"}
        if "symbol" in query:
            canonical["symbol"] = query["symbol"]
        provider = "bybit"
    else:
        if set(query) - {"listing_status", "start", "limit", "sort"}:
            raise IntakeRejected("CMC query contains a nonmetadata parameter")
        if "listing_status" not in query:
            raise IntakeRejected("CMC listing_status must be explicit; omission defaults to active only")
        statuses = query["listing_status"].split(",")
        if (not statuses or any(s not in STATUSES for s in statuses)
                or len(statuses) != len(set(statuses))):
            raise IntakeRejected("Unknown, empty or duplicate CMC listing status")
        if query.get("sort", "id") != "id":
            raise IntakeRejected("CMC metadata permits only sort=id")
        for name in ("start", "limit"):
            if name in query and not _POSITIVE_INT.fullmatch(query[name]):
                raise IntakeRejected("CMC pagination must use positive decimal integers")
        if "limit" in query and (len(query["limit"]) > 4 or int(query["limit"]) > 5000):
            raise IntakeRejected("CMC metadata limit exceeds 5000")
        status_coverage = [s for s in STATUSES if s in statuses]
        canonical = {"listing_status": ",".join(status_coverage), "sort": "id"}
        canonical.update({name: query[name] for name in ("start", "limit") if name in query})
        provider = "coinmarketcap"
    return {
        "schema": "nexus.ctrend-metadata-intake.v1", "provider": provider,
        "method": "GET",
        "canonical_url": urlunsplit(("https", parts.netloc, parts.path, urlencode(canonical), "")),
        "coverage": coverage, "coverage_is_caller_annotation_only": True,
        "status_coverage_requested": status_coverage,
        "all_cmc_statuses_requested": status_coverage == list(STATUSES),
        "response_received": False, **_authority_flags(),
    }


def check_response_metadata(payload):
    """Reject obvious market-data fields recursively; this is not authentication.

    Instrument metadata such as quoteCoin, priceFilter, minPrice, maxPrice and
    tickSize is permitted. The check deliberately does not interpret those as
    actual market quotes. It cannot detect every disguised market-data payload.
    """
    stack, seen, checked = [(payload, 0)], set(), 0
    while stack:
        item, depth = stack.pop()
        checked += 1
        if depth > 64 or checked > 100_000:
            raise IntakeRejected("Metadata payload exceeds the bounded structural check")
        if isinstance(item, (Mapping, list)):
            if id(item) in seen:
                raise IntakeRejected("Cyclic or aliased container is outside JSON metadata")
            seen.add(id(item))
            if isinstance(item, Mapping):
                for key, value in item.items():
                    if not isinstance(key, str):
                        raise IntakeRejected("Metadata field names must be strings")
                    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
                    obvious = (normalized in _MARKET_FIELDS
                               or normalized.startswith(("percentchange", "pricechange", "returns"))
                               or re.fullmatch(r"return[0-9].*", normalized)
                               or re.fullmatch(r"(?:open|high|low|close)(?:24h|1h|7d|30d)", normalized))
                    if obvious:
                        raise IntakeRejected("Obvious market-data field in metadata response")
                    stack.append((value, depth + 1))
            else:
                stack.extend((value, depth + 1) for value in item)
        elif not (item is None or isinstance(item, (str, bool, int, float))):
            raise IntakeRejected("Metadata payload must contain JSON-like values")
        elif isinstance(item, float) and not math.isfinite(item):
            raise IntakeRejected("Nonfinite JSON-like metadata value")
    return {"schema": "nexus.ctrend-metadata-response-check.v1",
            "obvious_market_fields_detected": False, "checked_nodes": checked,
            "complete_payload_security_validation": False,
            "provider_authenticity_verified": False, "provider_success_verified": False,
            **_authority_flags()}
