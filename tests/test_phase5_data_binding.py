from __future__ import annotations

from copy import deepcopy

import pytest

from market_data_provenance_manifest import build_provenance_manifest
import phase5_data_binding as binding

START = 1_640_995_200_000
ENDPOINT = "/v5/market/kline?category=spot&symbol=BTCUSDT&interval=15"


def candles():
    return [
        {"open_time_ms": START, "open": "47000", "high": "47100", "low": "46900", "close": "47050", "volume": "12.5"},
        {"open_time_ms": START + 900_000, "open": "47050", "high": "47200", "low": "47000", "close": "47150", "volume": "10.0"},
    ]


def manifest(*, source="Bybit", source_symbol="BTCUSDT", endpoint=ENDPOINT):
    rows = candles()
    return build_provenance_manifest(
        source=source,
        market_type="spot",
        source_symbol=source_symbol,
        canonical_symbol="BTC/USDT",
        timeframe="15m",
        endpoint_contract=endpoint,
        mapping_policy_version="1.0.0",
        retrieval_start_ms=START,
        retrieval_end_ms=START + 900_000,
        candles=rows,
    )


def test_valid_primary_binding_is_deterministic_and_explicit():
    first = binding.bind_canonical_dataset(manifest(), candles())
    second = binding.bind_canonical_dataset(manifest(), candles())
    assert first == second
    assert first["downstream_eligible"] is True
    assert first["paper_only"] is True
    assert first["source"] == "Bybit"
    assert first["source_role"] == "primary"
    assert first["instrument"] == "BTC/USDT"
    assert first["market"] == "spot"
    assert first["candidate_timeframe"] == "minute15"
    assert first["manifest_timeframe"] == "15m"
    assert first["interval"] == "15"
    assert first["finality"] == "closed_only"
    assert binding.validate_canonical_dataset(first) == first


def test_secondary_namespace_has_zero_gate6_eligibility():
    secondary = manifest(source="Binance", endpoint="/api/v3/klines?symbol=BTCUSDT&interval=15m")
    with pytest.raises(binding.CanonicalDataError, match="non-primary"):
        binding.bind_canonical_dataset(secondary, candles())


def test_unknown_endpoint_or_source_symbol_fails_closed():
    with pytest.raises(binding.CanonicalDataError):
        binding.bind_canonical_dataset(manifest(endpoint="/v5/market/kline?wrong=1"), candles())
    with pytest.raises(binding.CanonicalDataError):
        binding.bind_canonical_dataset(manifest(source_symbol="XBTUSDT"), candles())


def test_bound_artifact_tampering_is_rejected():
    artifact = binding.bind_canonical_dataset(manifest(), candles())
    for field, value in (("source", "Binance"), ("finality", "open_allowed"), ("interval", "60")):
        candidate = deepcopy(artifact)
        candidate[field] = value
        with pytest.raises(binding.CanonicalDataError):
            binding.validate_canonical_dataset(candidate)

    candidate = deepcopy(artifact)
    candidate["rows"][0]["close"] = "1"
    with pytest.raises(binding.CanonicalDataError):
        binding.validate_canonical_dataset(candidate)


def test_missing_or_ambiguous_provenance_is_never_eligible():
    with pytest.raises(binding.CanonicalDataError):
        binding.validate_canonical_dataset({"rows": candles(), "downstream_eligible": True})
