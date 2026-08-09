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


def _candidate(primary, secondary, *, status="eligible_candidate", selected_source="Bybit", timeframe="minute15"):
    return Candidate(
        symbol="btc_usdt",
        timeframe=timeframe,
        timestamp_utc="2024-03-10T00:00:00+00:00",
        status=status,
        selected_source=selected_source,
        primary_candle_sha256=_sha(_canonical(primary)),
        secondary_candle_sha256=_sha(_canonical(secondary)),
        max_ohlc_relative_deviation="0",
        reason="bybit_primary_binance_correlated",
    )


def _bind(candidate, primary, secondary, **overrides):
    kwargs = {
        "canonical_symbol": "BTC/USDT",
        "manifest_timeframe": "15m",
        "mapping_policy_version": "1.0.0",
        "primary_endpoint_contract": "/v5/market/kline?category=spot&symbol=BTCUSDT&interval=15",
        "secondary_endpoint_contract": "/api/v3/klines?symbol=BTCUSDT&interval=15m",
    }
    kwargs.update(overrides)
    return bind_candidate_provenance(
        candidate,
        primary_row=primary,
        secondary_row=secondary,
        **kwargs,
    )


def test_binding_is_deterministic_and_validates_both_source_manifests():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)

    first = _bind(candidate, primary, secondary)
    second = _bind(candidate, primary, secondary)

    assert first == second
    assert first["schema"] == "nexus.cross-source-reconciliation-provenance.v2"
    assert first["binding_sha256"]
    assert first["semantic_binding"]["candidate_timeframe"] == "minute15"
    assert first["semantic_binding"]["bybit_interval"] == "15"
    assert first["semantic_binding"]["binance_interval"] == "15m"
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


def test_timeframe_relabel_and_rehash_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, timeframe="minute15")

    with pytest.raises(ReconciliationProvenanceError, match="manifest timeframe mismatch"):
        _bind(candidate, primary, secondary, manifest_timeframe="1h")


def test_bybit_endpoint_interval_substitution_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="Bybit endpoint contract"):
        _bind(
            candidate,
            primary,
            secondary,
            primary_endpoint_contract="/v5/market/kline?category=spot&symbol=BTCUSDT&interval=60",
        )


def test_binance_endpoint_market_interval_substitution_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="Binance endpoint contract"):
        _bind(
            candidate,
            primary,
            secondary,
            secondary_endpoint_contract="/api/v3/klines?symbol=BTCUSDT&interval=1h",
        )


def test_unknown_mapping_policy_version_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="mapping policy version"):
        _bind(candidate, primary, secondary, mapping_policy_version="9.9.9")


def test_off_grid_timestamp_is_rejected_for_candidate_timeframe():
    primary, secondary = _row("Bybit", ts=1710028800001), _row("Binance", ts=1710028800001)
    candidate = _candidate(primary, secondary)

    with pytest.raises(ReconciliationProvenanceError, match="off-grid"):
        _bind(candidate, primary, secondary)


def test_hour1_requires_hour1_manifest_and_endpoint_semantics():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, timeframe="hour1")

    result = _bind(
        candidate,
        primary,
        secondary,
        manifest_timeframe="1h",
        primary_endpoint_contract="/v5/market/kline?category=spot&symbol=BTCUSDT&interval=60",
        secondary_endpoint_contract="/api/v3/klines?symbol=BTCUSDT&interval=1h",
    )
    assert result["semantic_binding"]["timestamp_grid_ms"] == 3_600_000


def test_unsupported_candidate_timeframe_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, timeframe="day1")

    with pytest.raises(ReconciliationProvenanceError, match="unsupported candidate timeframe"):
        _bind(candidate, primary, secondary)
