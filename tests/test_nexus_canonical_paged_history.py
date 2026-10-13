"""Physical canonical multi-page adapter contract; no fabricated market results."""
from __future__ import annotations

from copy import deepcopy

import pytest

from nexus_canonical_paged_history import (
    PAGED_15M_SCHEMA,
    REQUIRED_15M_BARS,
    fetch_verified_15m_window,
)
from phase5_data_binding import validate_canonical_dataset
from phase6_research_pipeline import bind_bybit_closed_dataset
from product_research_runtime import ProductResearchError, ProductResearchRuntime

STEP = 900_000
NOW = 1_900_000_000_000
END = ((NOW - STEP) // STEP) * STEP
START = END - (REQUIRED_15M_BARS - 1) * STEP


def _candles(start: int, count: int, symbol: str = "BTCUSDT"):
    return [{
        "source": "Bybit", "market_type": "spot", "symbol": symbol,
        "interval": "15", "open_time_ms": start + index * STEP,
        "close_time_ms": start + (index + 1) * STEP - 1,
        "open": "100.0", "high": "101.0", "low": "99.0",
        "close": "100.5", "volume": "10", "turnover": "1005",
        "closed": True,
    } for index in range(count)]


def _runtime(*, corrupt=None, now=NOW):
    calls = []

    def fetcher(**kwargs):
        calls.append(dict(kwargs))
        start, end, count = (
            kwargs["start_time_ms"], kwargs["end_time_ms"], kwargs["limit"]
        )
        assert kwargs["now_ms"] == now
        assert kwargs["interval"] == "15"
        assert kwargs["source_symbol"] == "BTCUSDT"
        assert end == start + (count - 1) * STEP
        assert 1 <= count <= 1000
        rows = _candles(start, count)
        if corrupt == "missing" and len(calls) == 2:
            rows = rows[:-1]
        elif corrupt == "overlap" and len(calls) == 2:
            rows[0]["open_time_ms"] -= STEP
        elif corrupt == "wrong_source" and len(calls) == 2:
            rows[0]["symbol"] = "ETHUSDT"
        # Fresh page is bound to the same semantic official registry contract.
        data = bind_bybit_closed_dataset(
            rows, canonical_symbol="BTC/USDT",
            source_symbol="BTCUSDT", interval="15",
        )
        if corrupt == "rehashed_trade" and len(calls) == 3:
            data["rows"][0]["open"] = "910.0"
        if corrupt == "time_shift" and len(calls) == 4:
            data["rows"][-1]["open_time_ms"] -= STEP
        return data

    runtime = ProductResearchRuntime(
        None, source_sha="a" * 40, dataset_fetcher=fetcher,
        clock_ms=lambda: now,
    )
    return runtime, calls


def test_exact_32_day_window_from_four_verified_api_pages():
    runtime, calls = _runtime()
    artifact = fetch_verified_15m_window(runtime, symbol="BTCUSDT")
    assert len(calls) == 4
    assert [call["limit"] for call in calls] == [1000, 1000, 1000, 72]
    assert artifact == validate_canonical_dataset(artifact)
    assert artifact["row_count"] == REQUIRED_15M_BARS
    assert artifact["rows"][0]["open_time_ms"] == START
    assert artifact["rows"][-1]["open_time_ms"] == END
    assert artifact["manifest"]["metadata"]["page_contract"] == PAGED_15M_SCHEMA
    assert len(artifact["manifest"]["metadata"]["page_bindings_sha256"]) == 4
    assert all(call["now_ms"] == NOW for call in calls)
    assert artifact["market"] == "spot"
    assert artifact["source_role"] == "primary"
    assert artifact["paper_only"] is True
    assert artifact["downstream_eligible"] is True
    # Bound SHA is independent of host network behavior or fetch order.
    assert fetch_verified_15m_window(_runtime()[0], symbol="BTCUSDT") == artifact


@pytest.mark.parametrize("corrupt", [
    "missing", "overlap", "wrong_source", "rehashed_trade", "time_shift"
])
def test_missing_stale_rehashed_or_substituted_pages_fail_closed(corrupt):
    runtime, calls = _runtime(corrupt=corrupt)
    with pytest.raises(ProductResearchError):
        fetch_verified_15m_window(runtime, symbol="BTCUSDT")
    assert len(calls) <= 4


def test_page_limit_clock_and_source_denied_before_network_call():
    runtime, calls = _runtime()
    for bad in (0, True, 1000, 2880, 5000):
        with pytest.raises(ProductResearchError, match="bounded"):
            fetch_verified_15m_window(runtime, symbol="BTCUSDT", limit=bad)
    with pytest.raises(ProductResearchError, match="mapping"):
        fetch_verified_15m_window(runtime, symbol="NOSUCHSYMBOL")
    assert calls == []
    bad_runtime, _ = _runtime(now=True)
    with pytest.raises(ProductResearchError, match="clock"):
        fetch_verified_15m_window(bad_runtime, symbol="BTCUSDT")


def test_provenance_digest_catches_stitched_mutations():
    artifact = fetch_verified_15m_window(_runtime()[0], symbol="BTCUSDT")
    forged = deepcopy(artifact)
    forged["rows"][2001]["close"] = "999.0"
    with pytest.raises(Exception, match="digest|manifest|provenance"):
        validate_canonical_dataset(forged)
