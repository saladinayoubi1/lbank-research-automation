from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any, Mapping

from cross_source_gap_reconciliation import Candidate
from market_data_provenance_manifest import build_provenance_manifest, validate_provenance_manifest
from market_data_source_validator import SourceContractValidationError, load_and_validate


CANONICAL_SOURCE_REGISTRY = Path("docs/architecture/market-data-source-registry.yaml")


class ReconciliationProvenanceError(ValueError):
    pass


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _canonical_candidate_candle(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {"source", "market_type", "symbol", "open_time_ms", "open", "high", "low", "close", "volume", "closed"}
    if not isinstance(row, Mapping) or not required.issubset(row):
        raise ReconciliationProvenanceError("source row schema incomplete")
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


def _manifest_candle(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "open_time_ms": row["open_time_ms"],
        "open": str(row["open"]),
        "high": str(row["high"]),
        "low": str(row["low"]),
        "close": str(row["close"]),
        "volume": str(row["volume"]),
    }


def _registry_mapping(candidate: Candidate, canonical_symbol: str) -> tuple[dict[str, Any], dict[str, dict[str, Any]], str]:
    try:
        registry = load_and_validate(CANONICAL_SOURCE_REGISTRY)
    except (OSError, SourceContractValidationError) as exc:
        raise ReconciliationProvenanceError(f"canonical source registry invalid: {exc}") from exc

    matches = [
        mapping
        for mapping in registry["mappings"]
        if mapping["canonical_symbol"] == canonical_symbol
        and mapping["timeframe"] == candidate.timeframe
        and mapping["market_category"] == "spot"
    ]
    if len(matches) != 1:
        raise ReconciliationProvenanceError("candidate has no unique canonical registry mapping")

    mapping = matches[0]
    sources = {source["exchange"]: source for source in mapping["sources"]}
    if set(sources) != {"Bybit", "Binance", "LBank"}:
        raise ReconciliationProvenanceError("canonical registry source tuple incomplete")
    if candidate.symbol != sources["LBank"]["symbol"]:
        raise ReconciliationProvenanceError("candidate symbol does not match canonical registry mapping")
    return mapping, sources, str(registry["registry_version"])


def bind_candidate_provenance(
    candidate: Candidate,
    *,
    primary_row: Mapping[str, Any],
    secondary_row: Mapping[str, Any],
    canonical_symbol: str,
    manifest_timeframe: str,
    mapping_policy_version: str,
    primary_endpoint_contract: str,
    secondary_endpoint_contract: str,
) -> dict[str, Any]:
    if candidate.status != "eligible_candidate" or candidate.selected_source != "Bybit":
        raise ReconciliationProvenanceError("candidate is not eligible for provenance binding")
    if not candidate.primary_candle_sha256 or not candidate.secondary_candle_sha256:
        raise ReconciliationProvenanceError("candidate candle digests are missing")

    mapping, sources, registry_version = _registry_mapping(candidate, canonical_symbol)
    bybit = sources["Bybit"]
    binance = sources["Binance"]

    expected_semantics = {
        "manifest_timeframe": mapping["manifest_timeframe"],
        "mapping_policy_version": mapping["mapping_policy_version"],
        "primary_endpoint_contract": bybit["endpoint_contract"],
        "secondary_endpoint_contract": binance["endpoint_contract"],
    }
    supplied_semantics = {
        "manifest_timeframe": manifest_timeframe,
        "mapping_policy_version": mapping_policy_version,
        "primary_endpoint_contract": primary_endpoint_contract,
        "secondary_endpoint_contract": secondary_endpoint_contract,
    }
    if supplied_semantics != expected_semantics:
        raise ReconciliationProvenanceError("caller-supplied semantic tuple does not match canonical registry")

    primary_canonical = _canonical_candidate_candle(primary_row)
    secondary_canonical = _canonical_candidate_candle(secondary_row)
    if primary_canonical["source"] != "Bybit" or secondary_canonical["source"] != "Binance":
        raise ReconciliationProvenanceError("source role mismatch")
    if primary_canonical["market_type"] != bybit["category"] or secondary_canonical["market_type"] != binance["market"]:
        raise ReconciliationProvenanceError("market type mismatch")
    if primary_canonical["symbol"] != bybit["symbol"] or secondary_canonical["symbol"] != binance["symbol"]:
        raise ReconciliationProvenanceError("source symbol does not match canonical registry")
    if primary_canonical["open_time_ms"] != secondary_canonical["open_time_ms"]:
        raise ReconciliationProvenanceError("source timestamp mismatch")
    if primary_canonical["closed"] is not True or secondary_canonical["closed"] is not True:
        raise ReconciliationProvenanceError("open or incomplete candle cannot be provenance-bound")

    open_time_ms = int(primary_canonical["open_time_ms"])
    if open_time_ms % int(mapping["timestamp_grid_ms"]) != 0:
        raise ReconciliationProvenanceError("source timestamp is off canonical timeframe grid")

    if _sha256(primary_canonical) != candidate.primary_candle_sha256:
        raise ReconciliationProvenanceError("primary candle digest mismatch")
    if _sha256(secondary_canonical) != candidate.secondary_candle_sha256:
        raise ReconciliationProvenanceError("secondary candle digest mismatch")

    primary_manifest = build_provenance_manifest(
        source="Bybit",
        market_type=bybit["category"],
        source_symbol=str(primary_canonical["symbol"]),
        canonical_symbol=canonical_symbol,
        timeframe=mapping["manifest_timeframe"],
        endpoint_contract=bybit["endpoint_contract"],
        mapping_policy_version=mapping["mapping_policy_version"],
        retrieval_start_ms=open_time_ms,
        retrieval_end_ms=open_time_ms,
        candles=[_manifest_candle(primary_row)],
        metadata={"role": "primary", "reconciliation_candidate_status": candidate.status},
    )
    secondary_manifest = build_provenance_manifest(
        source="Binance",
        market_type=binance["market"],
        source_symbol=str(secondary_canonical["symbol"]),
        canonical_symbol=canonical_symbol,
        timeframe=mapping["manifest_timeframe"],
        endpoint_contract=binance["endpoint_contract"],
        mapping_policy_version=mapping["mapping_policy_version"],
        retrieval_start_ms=open_time_ms,
        retrieval_end_ms=open_time_ms,
        candles=[_manifest_candle(secondary_row)],
        metadata={"role": "secondary", "reconciliation_candidate_status": candidate.status},
    )
    validate_provenance_manifest(primary_manifest, [_manifest_candle(primary_row)])
    validate_provenance_manifest(secondary_manifest, [_manifest_candle(secondary_row)])

    semantic_tuple = {
        "registry_version": registry_version,
        "mapping_id": mapping["mapping_id"],
        "candidate_timeframe": candidate.timeframe,
        "manifest_timeframe": mapping["manifest_timeframe"],
        "bybit_category": bybit["category"],
        "bybit_interval": bybit["interval"],
        "binance_market": binance["market"],
        "binance_interval": binance["interval"],
        "timestamp_grid_ms": mapping["timestamp_grid_ms"],
        "candle_finality": mapping["candle_finality"],
        "mapping_policy_version": mapping["mapping_policy_version"],
    }
    deterministic_core = {
        "schema": "nexus.cross-source-reconciliation-provenance.v2",
        "candidate": asdict(candidate),
        "canonical_symbol": canonical_symbol,
        "semantic_tuple": semantic_tuple,
        "primary_manifest_sha256": primary_manifest["manifest_sha256"],
        "secondary_manifest_sha256": secondary_manifest["manifest_sha256"],
    }
    return {
        **deterministic_core,
        "binding_sha256": _sha256(deterministic_core),
        "primary_manifest": primary_manifest,
        "secondary_manifest": secondary_manifest,
    }
