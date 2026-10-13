"""Canonical multi-page Bybit replay window for VAL-40; no new market runtime.

Every page is obtained from the *existing* official source-backed dataset fetcher
and independently canonical-validated. The final archive has a new, exact
immutable manifest containing all page source digests, and is validated again
before exposure. Neither missing candles nor partial/duplicate pages may be
smoothed or backfilled. This module cannot execute Paper or live orders.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from market_data_provenance_manifest import build_provenance_manifest
from phase5_data_binding import bind_canonical_dataset, validate_canonical_dataset
from product_research_runtime import (
    ProductResearchError,
    ProductResearchRuntime,
    TIMEFRAMES,
    _public_mapping,
    _registry_path,
)
from market_data_source_validator import load_and_validate

MAX_PAGE = 1000
REQUIRED_15M_BARS = 3072
PAGED_15M_SCHEMA = "nexus.canonical-paged-history.v1"


def fetch_verified_15m_window(
    runtime: ProductResearchRuntime, *, symbol: str, limit: int = REQUIRED_15M_BARS,
) -> dict[str, Any]:
    """Return 32 days of exact 15m closed bars, using <=1000 verified bars/page.

    Timestamp/namespace/semantic binding is identical to the existing canonical
    provider. The fixed count limits memory/network and prevents broad scans.
    """
    if type(limit) is not int or limit != REQUIRED_15M_BARS:
        raise ProductResearchError("unsupported bounded 15m observation window size")
    spec = TIMEFRAMES["minute15"]
    step = int(spec["step_ms"])
    try:
        registry = load_and_validate(_registry_path())
        mapping, source = _public_mapping(registry, symbol, "minute15")
    except (OSError, KeyError, ValueError) as exc:
        raise ProductResearchError("canonical 15m source mapping unavailable") from exc
    now_ms = runtime.clock_ms()
    if type(now_ms) is not int or now_ms <= 0:
        raise ProductResearchError("canonical runtime clock invalid")
    end = ((now_ms - step) // step) * step
    start = end - (limit - 1) * step
    if start < 0:
        raise ProductResearchError("invalid bounded 15m start time")
    rows: list[dict[str, Any]] = []
    page_digests: list[str] = []
    immutable_identity: tuple[Any, ...] | None = None
    for offset in range(0, limit, MAX_PAGE):
        count = min(MAX_PAGE, limit - offset)
        page_start = start + offset * step
        page_end = page_start + (count - 1) * step
        try:
            page = runtime.dataset_fetcher(
                canonical_symbol=mapping["canonical_symbol"],
                source_symbol=source["symbol"],
                interval=spec["interval"],
                now_ms=now_ms,
                start_time_ms=page_start,
                end_time_ms=page_end,
                limit=count,
                timeout_seconds=20.0,
            )
            artifact = validate_canonical_dataset(page, registry_path=_registry_path())
        except Exception as exc:
            raise ProductResearchError(
                "canonical paged 15m Bybit source unavailable/incomplete"
            ) from exc
        if artifact["row_count"] != count or len(artifact["rows"]) != count:
            raise ProductResearchError("canonical 15m page incomplete or overfilled")
        if (
            type(artifact["rows"][0]["open_time_ms"]) is not int
            or type(artifact["rows"][-1]["open_time_ms"]) is not int
            or artifact["rows"][0]["open_time_ms"] != page_start
            or artifact["rows"][-1]["open_time_ms"] != page_end
        ):
            raise ProductResearchError("canonical 15m page timestamp bounds mismatch")
        identity = (
            artifact["instrument"], artifact["source"], artifact["source_role"],
            artifact["source_symbol"], artifact["interval"], artifact["market"],
            artifact["mapping_id"], artifact["mapping_policy_version"],
            artifact["registry_version"], artifact["endpoint_contract"],
        )
        if immutable_identity is None:
            immutable_identity = identity
        elif identity != immutable_identity:
            raise ProductResearchError("canonical 15m pages have inconsistent semantic mapping")
        rows.extend(artifact["rows"])
        page_digests.append(artifact["binding_sha256"])
    if (
        len(rows) != limit or len(page_digests) != 4
        or rows[0]["open_time_ms"] != start
        or rows[-1]["open_time_ms"] != end
        or any(rows[index]["open_time_ms"] != start + index * step
               for index in range(len(rows)))
    ):
        raise ProductResearchError("stitched canonical Bybit history has a gap/duplicate")
    try:
        manifest = build_provenance_manifest(
            source="Bybit",
            market_type="spot",
            source_symbol=source["symbol"],
            canonical_symbol=mapping["canonical_symbol"],
            timeframe=spec["manifest"],
            endpoint_contract=source["endpoint_contract"],
            mapping_policy_version=mapping["mapping_policy_version"],
            retrieval_start_ms=start,
            retrieval_end_ms=end,
            candles=rows,
            metadata={
                "collector": "bybit_public_klines",
                "closed_only": True,
                "page_contract": PAGED_15M_SCHEMA,
                "page_bindings_sha256": page_digests,
                "page_size_limit": MAX_PAGE,
            },
        )
        assembled = bind_canonical_dataset(
            manifest, rows, registry_path=_registry_path()
        )
        verified = validate_canonical_dataset(
            assembled, registry_path=_registry_path()
        )
    except Exception as exc:
        raise ProductResearchError("stitched canonical 15m archive verification failed") from exc
    age_ms = now_ms - (end + step)
    if age_ms < 0 or age_ms >= step:
        raise ProductResearchError("stitched newest 15m bar not exactly latest closed")
    return verified
