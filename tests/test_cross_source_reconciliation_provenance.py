import hashlib
import json

import pytest

from cross_source_gap_reconciliation import Candidate
from cross_source_reconciliation_provenance import ReconciliationProvenanceError, bind_candidate_provenance


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _row(source, *, close="100", ts=1710028800000):
    return {
        "source": source,
        "market_type": "spot",
        "symbol": "BTCUSDT",
        "open_time_ms": ts,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
        "closed": True,
    }


def _canonical(row):
    return {
        "source": row["source"],
        "market_type": row["market_type"],
        "symbol": row["symbol"],
        "open_time_ms": row["open_time_ms"],
        "open": str(row["open"]),
        "high": str(row["high"]),
        "low": str(row["low"]),
        "close": str(row["close"]),
        "volume": str(row["volume"]),
        "closed": row["closed"],
    }


def _candidate(primary, secondary, *, status="eligible_candidate", selected_source="Bybit"):
    return Candidate(
        symbol="btc_usdt",
        timeframe="minute15",
        timestamp_utc="2024-03-10T00:00:00+00:00",
        status=status,
        selected_source=selected_source,
        primary_candle_sha256=_sha(_canonical(primary)),
        secondary_candle_sha256=_sha(_canonical(secondary)),
        max_ohlc_relative_deviation="0",
        reason="bybit_primary_binance_correlated",
    )


def _bind(candidate, primary, secondary):
    return bind_candidate_provenance(
        candidate,
        primary_row=primary,
        secondary_row=secondary,
        canonical_symbol="BTC/USDT",
        manifest_timeframe="15m",
        mapping_policy_version="1.0.0",
        primary_endpoint_contract="/v5/market/kline?category=spot&symbol=BTCUSDT&interval=15",
        secondary_endpoint_contract="/api/v3/klines?symbol=BTCUSDT&interval=15m",
    )


def test_binding_is_deterministic_and_validates_both_source_manifests():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)

    first = _bind(candidate, primary, secondary)
    second = _bind(candidate, primary, secondary)

    assert first == second
    assert first["binding_sha256"]
    assert first["primary_manifest"]["source"] == "Bybit"
    assert first["secondary_manifest"]["source"] == "Binance"
    assert first["primary_manifest_sha256"] == first["primary_manifest"]["manifest_sha256"]
    assert first["secondary_manifest_sha256"] == first["secondary_manifest"]["manifest_sha256"]


def test_tampered_primary_candle_is_rejected_fail_closed():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)
    tampered = dict(primary)
    tampered["close"] = "101"

    with pytest.raises(ReconciliationProvenanceError, match="primary candle digest mismatch"):
        _bind(candidate, tampered, secondary)


def test_blocked_candidate_cannot_be_provenance_bound():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, status="blocked", selected_source=None)

    with pytest.raises(ReconciliationProvenanceError, match="not eligible"):
        _bind(candidate, primary, secondary)


def test_open_candle_is_rejected_even_if_candidate_digest_matches():
    primary, secondary = _row("Bybit"), _row("Binance")
    primary["closed"] = False
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="open or incomplete"):
        _bind(candidate, primary, secondary)


def test_source_role_swap_is_rejected():
    primary, secondary = _row("Binance"), _row("Bybit")
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="source role mismatch"):
        _bind(candidate, primary, secondary)
