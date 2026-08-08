from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any


MANIFEST_SCHEMA = "nexus.market-data-provenance.v1"
ALLOWED_SOURCES = {"Bybit", "Binance", "LBank"}
ALLOWED_MARKET_TYPES = {"spot", "perpetual", "futures"}
SUPPORTED_TIMEFRAMES_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "3d": 259_200_000,
    "1w": 604_800_000,
}
REQUIRED_CANDLE_FIELDS = (
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
)
FORBIDDEN_METADATA_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "cookies",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "token",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ProvenanceManifestError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _validate_text(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceManifestError(f"{name} must be a non-empty string")
    return value


def _validate_non_negative_int(name: str, value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProvenanceManifestError(f"{name} must be a non-negative integer")
    return value


def _timeframe_interval_ms(timeframe: Any) -> int:
    timeframe = _validate_text("timeframe", timeframe)
    try:
        return SUPPORTED_TIMEFRAMES_MS[timeframe]
    except KeyError as exc:
        raise ProvenanceManifestError("unsupported timeframe") from exc


def _reject_sensitive_metadata(value: Any, *, path: str = "metadata") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ProvenanceManifestError(f"{path} keys must be strings")
            normalized = key.strip().lower().replace("-", "_")
            if normalized in FORBIDDEN_METADATA_KEYS:
                raise ProvenanceManifestError(f"sensitive metadata key is prohibited: {key}")
            _reject_sensitive_metadata(nested, path=f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_sensitive_metadata(nested, path=f"{path}[{index}]")


def _normalize_candles(
    candles: Sequence[Mapping[str, Any]], *, interval_ms: int
) -> list[dict[str, Any]]:
    if isinstance(candles, (str, bytes, bytearray)) or not isinstance(candles, Sequence):
        raise ProvenanceManifestError("candles must be a sequence of mappings")
    if not candles:
        raise ProvenanceManifestError("candles must not be empty")

    normalized: list[dict[str, Any]] = []
    previous_open: int | None = None
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping):
            raise ProvenanceManifestError(f"candle {index} must be a mapping")
        missing = [field for field in REQUIRED_CANDLE_FIELDS if field not in candle]
        if missing:
            raise ProvenanceManifestError(f"candle {index} missing fields: {','.join(missing)}")
        open_time = _validate_non_negative_int(f"candle {index} open_time_ms", candle["open_time_ms"])
        if open_time % interval_ms != 0:
            raise ProvenanceManifestError("candle timestamp is off the declared timeframe grid")
        if previous_open is not None:
            if open_time <= previous_open:
                raise ProvenanceManifestError("candle timestamps must be strictly increasing")
            if open_time - previous_open != interval_ms:
                raise ProvenanceManifestError("candle cadence does not match the declared timeframe")
        previous_open = open_time
        normalized.append({field: candle[field] for field in REQUIRED_CANDLE_FIELDS})
    return normalized


def _validate_window_completeness(
    *, retrieval_start_ms: int, retrieval_end_ms: int, interval_ms: int, normalized_candles: list[dict[str, Any]]
) -> None:
    if retrieval_start_ms % interval_ms != 0 or retrieval_end_ms % interval_ms != 0:
        raise ProvenanceManifestError("retrieval window is off the declared timeframe grid")
    if retrieval_end_ms < retrieval_start_ms:
        raise ProvenanceManifestError("retrieval_end_ms cannot be before retrieval_start_ms")
    if (retrieval_end_ms - retrieval_start_ms) % interval_ms != 0:
        raise ProvenanceManifestError("retrieval window does not align to the declared timeframe")

    first_open = normalized_candles[0]["open_time_ms"]
    last_open = normalized_candles[-1]["open_time_ms"]
    if first_open != retrieval_start_ms or last_open != retrieval_end_ms:
        raise ProvenanceManifestError("candles do not completely cover the declared retrieval window")
    expected_count = ((retrieval_end_ms - retrieval_start_ms) // interval_ms) + 1
    if len(normalized_candles) != expected_count:
        raise ProvenanceManifestError("candle count does not completely cover the declared retrieval window")


def build_provenance_manifest(
    *,
    source: str,
    market_type: str,
    source_symbol: str,
    canonical_symbol: str,
    timeframe: str,
    endpoint_contract: str,
    mapping_policy_version: str,
    retrieval_start_ms: int,
    retrieval_end_ms: int,
    candles: Sequence[Mapping[str, Any]],
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = _validate_text("source", source)
    if source not in ALLOWED_SOURCES:
        raise ProvenanceManifestError("unsupported source")
    market_type = _validate_text("market_type", market_type)
    if market_type not in ALLOWED_MARKET_TYPES:
        raise ProvenanceManifestError("unsupported market_type")
    source_symbol = _validate_text("source_symbol", source_symbol)
    canonical_symbol = _validate_text("canonical_symbol", canonical_symbol)
    interval_ms = _timeframe_interval_ms(timeframe)
    timeframe = _validate_text("timeframe", timeframe)
    endpoint_contract = _validate_text("endpoint_contract", endpoint_contract)
    mapping_policy_version = _validate_text("mapping_policy_version", mapping_policy_version)

    retrieval_start_ms = _validate_non_negative_int("retrieval_start_ms", retrieval_start_ms)
    retrieval_end_ms = _validate_non_negative_int("retrieval_end_ms", retrieval_end_ms)
    normalized_candles = _normalize_candles(candles, interval_ms=interval_ms)
    _validate_window_completeness(
        retrieval_start_ms=retrieval_start_ms,
        retrieval_end_ms=retrieval_end_ms,
        interval_ms=interval_ms,
        normalized_candles=normalized_candles,
    )

    first_open = normalized_candles[0]["open_time_ms"]
    last_open = normalized_candles[-1]["open_time_ms"]

    if metadata is not None and not isinstance(metadata, Mapping):
        raise ProvenanceManifestError("metadata must be a mapping")
    metadata_value: dict[str, Any] = dict(metadata or {})
    _reject_sensitive_metadata(metadata_value)
    _canonical_json(metadata_value)

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source": source,
        "market_type": market_type,
        "source_symbol": source_symbol,
        "canonical_symbol": canonical_symbol,
        "timeframe": timeframe,
        "endpoint_contract": endpoint_contract,
        "mapping_policy_version": mapping_policy_version,
        "retrieval_window": {
            "start_ms": retrieval_start_ms,
            "end_ms": retrieval_end_ms,
        },
        "candle_count": len(normalized_candles),
        "first_open_time_ms": first_open,
        "last_open_time_ms": last_open,
        "candles_sha256": _digest(normalized_candles),
        "metadata": metadata_value,
    }
    manifest["manifest_sha256"] = _digest(manifest)
    return manifest


def validate_provenance_manifest(manifest: Mapping[str, Any], candles: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(manifest, Mapping):
        raise ProvenanceManifestError("manifest must be a mapping")
    if set(manifest) != {
        "schema",
        "source",
        "market_type",
        "source_symbol",
        "canonical_symbol",
        "timeframe",
        "endpoint_contract",
        "mapping_policy_version",
        "retrieval_window",
        "candle_count",
        "first_open_time_ms",
        "last_open_time_ms",
        "candles_sha256",
        "metadata",
        "manifest_sha256",
    }:
        raise ProvenanceManifestError("manifest fields do not match the exact schema")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ProvenanceManifestError("unsupported manifest schema")

    source = _validate_text("source", manifest["source"])
    if source not in ALLOWED_SOURCES:
        raise ProvenanceManifestError("unsupported source")
    market_type = _validate_text("market_type", manifest["market_type"])
    if market_type not in ALLOWED_MARKET_TYPES:
        raise ProvenanceManifestError("unsupported market_type")
    for field in ("source_symbol", "canonical_symbol", "endpoint_contract", "mapping_policy_version"):
        _validate_text(field, manifest[field])
    interval_ms = _timeframe_interval_ms(manifest["timeframe"])

    retrieval_window = manifest["retrieval_window"]
    if not isinstance(retrieval_window, Mapping) or set(retrieval_window) != {"start_ms", "end_ms"}:
        raise ProvenanceManifestError("retrieval_window does not match the exact schema")
    retrieval_start_ms = _validate_non_negative_int("retrieval_window.start_ms", retrieval_window["start_ms"])
    retrieval_end_ms = _validate_non_negative_int("retrieval_window.end_ms", retrieval_window["end_ms"])

    normalized_candles = _normalize_candles(candles, interval_ms=interval_ms)
    _validate_window_completeness(
        retrieval_start_ms=retrieval_start_ms,
        retrieval_end_ms=retrieval_end_ms,
        interval_ms=interval_ms,
        normalized_candles=normalized_candles,
    )

    first_open = normalized_candles[0]["open_time_ms"]
    last_open = normalized_candles[-1]["open_time_ms"]
    if manifest["candle_count"] != len(normalized_candles):
        raise ProvenanceManifestError("candle_count mismatch")
    if manifest["first_open_time_ms"] != first_open:
        raise ProvenanceManifestError("first_open_time_ms mismatch")
    if manifest["last_open_time_ms"] != last_open:
        raise ProvenanceManifestError("last_open_time_ms mismatch")
    candles_digest = manifest["candles_sha256"]
    if not isinstance(candles_digest, str) or not _SHA256_RE.fullmatch(candles_digest):
        raise ProvenanceManifestError("candles_sha256 is malformed")
    if candles_digest != _digest(normalized_candles):
        raise ProvenanceManifestError("candles_sha256 mismatch")

    metadata = manifest["metadata"]
    if not isinstance(metadata, Mapping):
        raise ProvenanceManifestError("metadata must be a mapping")
    _reject_sensitive_metadata(metadata)
    _canonical_json(metadata)

    unsigned = dict(manifest)
    claimed = unsigned.pop("manifest_sha256")
    if not isinstance(claimed, str) or not _SHA256_RE.fullmatch(claimed):
        raise ProvenanceManifestError("manifest_sha256 is malformed")
    if claimed != _digest(unsigned):
        raise ProvenanceManifestError("manifest_sha256 mismatch")
