import hashlib
import json

import pytest

from cross_source_gap_reconciliation import Candidate
from cross_source_reconciliation_provenance import ReconciliationProvenanceError, bind_candidate_provenance


def _sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _row(source, *, close="100", ts=1710028800000, symbol="BTCUSDT", market_type="spot"):
    return {
        "source": source,
        "market_type": market_type,
        "symbol": symbol,
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


def _candidate(primary, secondary, *, status="eligible_candidate", selected_source="Bybit", symbol="btc_usdt", timeframe="minute15"):
    return Candidate(
        symbol=symbol,
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
    return bind_candidate_provenance(candidate, primary_row=primary, secondary_row=secondary, **kwargs)


def test_binding_is_deterministic_and_validates_both_source_manifests():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)
    first = _bind(candidate, primary, secondary)
    second = _bind(candidate, primary, secondary)
    assert first == second
    assert first["schema"] == "nexus.cross-source-reconciliation-provenance.v2"
    assert first["binding_sha256"]
    assert first["semantic_tuple"] == {
        "registry_version": "1.1.0",
        "mapping_id": "btc-usdt-spot-minute15-v1",
        "candidate_timeframe": "minute15",
        "manifest_timeframe": "15m",
        "bybit_category": "spot",
        "bybit_interval": "15",
        "binance_market": "spot",
        "binance_interval": "15m",
        "timestamp_grid_ms": 900000,
        "candle_finality": "closed_only",
        "mapping_policy_version": "1.0.0",
    }
    assert first["primary_manifest"]["source"] == "Bybit"
    assert first["secondary_manifest"]["source"] == "Binance"
    assert first["primary_manifest_sha256"] == first["primary_manifest"]["manifest_sha256"]
    assert first["secondary_manifest_sha256"] == first["secondary_manifest"]["manifest_sha256"]


def test_tampered_primary_candle_is_rejected_fail_closed():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)
    tampered = dict(primary); tampered["close"] = "101"
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


@pytest.mark.parametrize("overrides", [
    {"manifest_timeframe": "1h"},
    {"mapping_policy_version": "0.9.0"},
    {"primary_endpoint_contract": "/v5/market/kline?category=linear&symbol=BTCUSDT&interval=15"},
    {"secondary_endpoint_contract": "/fapi/v1/klines?symbol=BTCUSDT&interval=15m"},
])
def test_caller_supplied_semantic_substitution_is_rejected(overrides):
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary)
    with pytest.raises(ReconciliationProvenanceError, match="caller-supplied semantic tuple"):
        _bind(candidate, primary, secondary, **overrides)


def test_timeframe_relabel_is_rejected_by_registry_mapping():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, timeframe="hour1")
    with pytest.raises(ReconciliationProvenanceError):
        _bind(candidate, primary, secondary)


def test_candidate_symbol_alias_substitution_is_rejected():
    primary, secondary = _row("Bybit"), _row("Binance")
    candidate = _candidate(primary, secondary, symbol="BTCUSDT")
    with pytest.raises(ReconciliationProvenanceError, match="candidate symbol"):
        _bind(candidate, primary, secondary)


def test_source_symbol_substitution_is_rejected_even_with_matching_digest():
    primary, secondary = _row("Bybit", symbol="BTC-USDT"), _row("Binance")
    candidate = _candidate(primary, secondary)
    with pytest.raises(ReconciliationProvenanceError, match="source symbol"):
        _bind(candidate, primary, secondary)


def test_market_category_substitution_is_rejected_even_with_matching_digest():
    primary, secondary = _row("Bybit", market_type="linear"), _row("Binance")
    candidate = _candidate(primary, secondary)
    with pytest.raises(ReconciliationProvenanceError, match="market type mismatch"):
        _bind(candidate, primary, secondary)


def test_off_grid_timestamp_is_rejected_even_with_matching_digest():
    primary = _row("Bybit", ts=1710028800001)
    secondary = _row("Binance", ts=1710028800001)
    candidate = _candidate(primary, secondary)
    with pytest.raises(ReconciliationProvenanceError, match="off canonical timeframe grid"):
        _bind(candidate, primary, secondary)
