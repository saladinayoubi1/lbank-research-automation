from __future__ import annotations

import copy
import hashlib
import json

import pytest

from market_data_provenance_manifest import (
    ProvenanceManifestError,
    build_provenance_manifest,
    validate_provenance_manifest,
)


def _candles() -> list[dict[str, object]]:
    return [
        {
            "open_time_ms": 0,
            "open": "100",
            "high": "110",
            "low": "90",
            "close": "105",
            "volume": "12.5",
        },
        {
            "open_time_ms": 900_000,
            "open": "105",
            "high": "112",
            "low": "101",
            "close": "108",
            "volume": "9.25",
        },
    ]


def _manifest(candles: list[dict[str, object]] | None = None, **overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "source": "Binance",
        "market_type": "spot",
        "source_symbol": "BTCUSDT",
        "canonical_symbol": "BTC/USDT",
        "timeframe": "15m",
        "endpoint_contract": "binance-spot-rest-api-v3-klines",
        "mapping_policy_version": "1.0.0",
        "retrieval_start_ms": 0,
        "retrieval_end_ms": 900_000,
        "candles": candles or _candles(),
        "metadata": {"adapter": "binance_public_klines", "public_data": True},
    }
    args.update(overrides)
    return build_provenance_manifest(**args)  # type: ignore[arg-type]


def _resign_untrusted_manifest(manifest: dict[str, object]) -> None:
    unsigned = dict(manifest)
    unsigned.pop("manifest_sha256", None)
    payload = json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    manifest["manifest_sha256"] = hashlib.sha256(payload).hexdigest()


def test_manifest_is_deterministic_and_validates() -> None:
    candles = _candles()
    first = _manifest(candles)
    second = _manifest(copy.deepcopy(candles))
    assert first == second
    assert first["candles_sha256"] == second["candles_sha256"]
    assert first["manifest_sha256"] == second["manifest_sha256"]
    validate_provenance_manifest(first, candles)


def test_rejects_candle_tamper() -> None:
    candles = _candles()
    manifest = _manifest(candles)
    tampered = copy.deepcopy(candles)
    tampered[1]["close"] = "999"
    with pytest.raises(ProvenanceManifestError, match="candles_sha256 mismatch"):
        validate_provenance_manifest(manifest, tampered)


def test_rejects_manifest_metadata_tamper() -> None:
    candles = _candles()
    manifest = _manifest(candles)
    manifest["metadata"] = {"adapter": "substituted"}
    with pytest.raises(ProvenanceManifestError, match="manifest_sha256 mismatch"):
        validate_provenance_manifest(manifest, candles)


def test_rejects_sensitive_metadata_recursively() -> None:
    with pytest.raises(ProvenanceManifestError, match="sensitive metadata key"):
        _manifest(metadata={"nested": {"Authorization": "Bearer should-not-persist"}})
    with pytest.raises(ProvenanceManifestError, match="sensitive metadata key"):
        _manifest(metadata={"nested": {"access-token": "should-not-persist"}})


def test_rejects_out_of_order_or_duplicate_candles() -> None:
    candles = _candles()
    candles.append(copy.deepcopy(candles[-1]))
    with pytest.raises(ProvenanceManifestError, match="strictly increasing"):
        _manifest(candles)


def test_rejects_candles_outside_declared_retrieval_window() -> None:
    with pytest.raises(ProvenanceManifestError, match="outside the declared retrieval window"):
        _manifest(retrieval_start_ms=1)


def test_rejects_self_consistent_window_substitution() -> None:
    candles = _candles()
    manifest = _manifest(candles)
    manifest["retrieval_window"] = {"start_ms": 1, "end_ms": 900_000}
    _resign_untrusted_manifest(manifest)
    with pytest.raises(ProvenanceManifestError, match="outside the declared retrieval window"):
        validate_provenance_manifest(manifest, candles)


def test_rejects_self_consistent_unsupported_source() -> None:
    candles = _candles()
    manifest = _manifest(candles)
    manifest["source"] = "SubstitutedExchange"
    _resign_untrusted_manifest(manifest)
    with pytest.raises(ProvenanceManifestError, match="unsupported source"):
        validate_provenance_manifest(manifest, candles)


def test_rejects_unknown_manifest_fields_fail_closed() -> None:
    candles = _candles()
    manifest = _manifest(candles)
    manifest["unexpected"] = True
    with pytest.raises(ProvenanceManifestError, match="exact schema"):
        validate_provenance_manifest(manifest, candles)


def test_rejects_unsupported_source_and_market_type() -> None:
    with pytest.raises(ProvenanceManifestError, match="unsupported source"):
        _manifest(source="UnknownExchange")
    with pytest.raises(ProvenanceManifestError, match="unsupported market_type"):
        _manifest(market_type="margin")
