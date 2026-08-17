from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from market_data_provenance_manifest import ProvenanceManifestError, validate_provenance_manifest
from market_data_source_validator import SourceContractValidationError, load_and_validate

DATASET_SCHEMA = "nexus.phase5-canonical-dataset.v1"
REGISTRY_PATH = Path("docs/architecture/market-data-source-registry.yaml")


class CanonicalDataError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonicalDataError("value is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _source_interval(source: Mapping[str, Any], mapping: Mapping[str, Any]) -> str:
    if source["exchange"] in {"Bybit", "Binance"}:
        return str(source["interval"])
    return str(mapping["timeframe"])


def _resolve_semantics(manifest: Mapping[str, Any], registry_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        registry = load_and_validate(registry_path)
    except (SourceContractValidationError, OSError) as exc:
        raise CanonicalDataError(f"canonical registry invalid: {exc}") from exc
    matches = [
        mapping for mapping in registry["mappings"]
        if mapping["canonical_symbol"] == manifest["canonical_symbol"]
        and mapping["market_category"] == manifest["market_type"]
        and mapping["manifest_timeframe"] == manifest["timeframe"]
        and mapping["mapping_policy_version"] == manifest["mapping_policy_version"]
    ]
    if len(matches) != 1:
        raise CanonicalDataError("manifest has no unique canonical semantic mapping")
    mapping = matches[0]
    sources = [source for source in mapping["sources"] if source["exchange"] == manifest["source"] and source["symbol"] == manifest["source_symbol"]]
    if len(sources) != 1:
        raise CanonicalDataError("manifest source namespace is not canonical for mapping")
    source = sources[0]
    if source["role"] != "primary" or source["exchange"] != registry["authority"]["primary"]:
        raise CanonicalDataError("non-primary source has zero downstream eligibility")
    if source["status"] != "compatible":
        raise CanonicalDataError("canonical primary source is not compatible")
    if source["category"] != mapping["market_category"]:
        raise CanonicalDataError("source category does not match mapping")
    if source["endpoint_contract"] != manifest["endpoint_contract"]:
        raise CanonicalDataError("endpoint semantics do not match canonical registry")
    return registry, mapping, source


def bind_canonical_dataset(manifest: Mapping[str, Any], candles: list[Mapping[str, Any]], *, registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    """Bind validated primary data to the canonical Gate-7 semantic registry."""
    try:
        validate_provenance_manifest(manifest, candles)
    except ProvenanceManifestError as exc:
        raise CanonicalDataError(f"provenance manifest invalid: {exc}") from exc
    registry, mapping, source = _resolve_semantics(manifest, registry_path)
    rows = [{field: row[field] for field in ("open_time_ms", "open", "high", "low", "close", "volume")} for row in candles]
    core = {
        "schema_version": DATASET_SCHEMA,
        "downstream_eligible": True,
        "paper_only": True,
        "registry_version": registry["registry_version"],
        "mapping_id": mapping["mapping_id"],
        "instrument": mapping["canonical_symbol"],
        "market": mapping["market_category"],
        "source": source["exchange"],
        "source_role": source["role"],
        "source_symbol": source["symbol"],
        "candidate_timeframe": mapping["timeframe"],
        "manifest_timeframe": mapping["manifest_timeframe"],
        "interval": _source_interval(source, mapping),
        "category": source["category"],
        "timestamp_convention": mapping["timestamp_convention"],
        "timestamp_grid_ms": mapping["timestamp_grid_ms"],
        "finality": mapping["candle_finality"],
        "mapping_policy_version": mapping["mapping_policy_version"],
        "endpoint_contract": source["endpoint_contract"],
        "manifest_sha256": manifest["manifest_sha256"],
        "candles_sha256": manifest["candles_sha256"],
        "row_count": len(rows),
        "manifest": dict(manifest),
        "rows": rows,
    }
    return {**core, "binding_sha256": _digest(core)}


def validate_canonical_dataset(artifact: Mapping[str, Any], *, registry_path: Path = REGISTRY_PATH) -> dict[str, Any]:
    if not isinstance(artifact, Mapping):
        raise CanonicalDataError("dataset artifact must be a mapping")
    required = {
        "schema_version", "downstream_eligible", "paper_only", "registry_version", "mapping_id",
        "instrument", "market", "source", "source_role", "source_symbol", "candidate_timeframe",
        "manifest_timeframe", "interval", "category", "timestamp_convention", "timestamp_grid_ms",
        "finality", "mapping_policy_version", "endpoint_contract", "manifest_sha256", "candles_sha256",
        "row_count", "manifest", "rows", "binding_sha256",
    }
    if set(artifact) != required or artifact.get("schema_version") != DATASET_SCHEMA:
        raise CanonicalDataError("dataset artifact schema mismatch")
    if artifact.get("downstream_eligible") is not True or artifact.get("paper_only") is not True:
        raise CanonicalDataError("dataset is not downstream eligible within paper scope")
    rows = artifact.get("rows")
    manifest = artifact.get("manifest")
    if not isinstance(rows, list) or not rows or artifact.get("row_count") != len(rows) or not isinstance(manifest, Mapping):
        raise CanonicalDataError("dataset manifest/rows are missing or inconsistent")
    try:
        validate_provenance_manifest(manifest, rows)
    except ProvenanceManifestError as exc:
        raise CanonicalDataError(f"embedded provenance manifest invalid: {exc}") from exc
    registry, mapping, source = _resolve_semantics(manifest, registry_path)
    expected = {
        "registry_version": registry["registry_version"], "mapping_id": mapping["mapping_id"],
        "instrument": mapping["canonical_symbol"], "market": mapping["market_category"],
        "source": source["exchange"], "source_role": source["role"], "source_symbol": source["symbol"],
        "candidate_timeframe": mapping["timeframe"], "manifest_timeframe": mapping["manifest_timeframe"],
        "interval": _source_interval(source, mapping), "category": source["category"],
        "timestamp_convention": mapping["timestamp_convention"], "timestamp_grid_ms": mapping["timestamp_grid_ms"],
        "finality": mapping["candle_finality"], "mapping_policy_version": mapping["mapping_policy_version"],
        "endpoint_contract": source["endpoint_contract"], "manifest_sha256": manifest["manifest_sha256"],
        "candles_sha256": manifest["candles_sha256"], "row_count": len(rows),
    }
    for field, value in expected.items():
        if artifact.get(field) != value:
            raise CanonicalDataError(f"dataset semantic field mismatch: {field}")
    core = dict(artifact)
    claimed = core.pop("binding_sha256")
    if not isinstance(claimed, str) or len(claimed) != 64 or _digest(core) != claimed:
        raise CanonicalDataError("dataset binding digest mismatch")
    return dict(artifact)
