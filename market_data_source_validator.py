from __future__ import annotations

import argparse
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, DocumentStartEvent, ScalarEvent

MAX_REGISTRY_BYTES = 128_000
MAX_MAPPINGS = 1_000
SUPPORTED_PYYAML_MAJOR = 6

ROOT_KEYS = {"registry_version", "status", "scope", "issue", "adr", "authority", "mappings"}
AUTHORITY_KEYS = {
    "primary",
    "secondary",
    "tertiary",
    "silent_cross_exchange_substitution",
    "live_trading",
    "private_credentials",
    "unknown_mapping",
    "failed_candidate_replaces_previous_valid",
}
MAPPING_KEYS = {
    "mapping_id",
    "canonical_symbol",
    "market_category",
    "quote_asset",
    "settlement_asset",
    "timeframe",
    "timestamp_convention",
    "candle_finality",
    "listing_start_utc",
    "listing_end_utc",
    "volume_semantics",
    "mapping_policy_version",
    "sources",
}
SOURCE_KEYS = {"exchange", "role", "symbol", "category", "endpoint_contract", "status"}

EXPECTED_AUTHORITY = {
    "primary": "Bybit",
    "secondary": "Binance",
    "tertiary": "LBank",
    "silent_cross_exchange_substitution": "prohibited",
    "live_trading": "prohibited",
    "private_credentials": "prohibited",
    "unknown_mapping": "reject",
    "failed_candidate_replaces_previous_valid": False,
}
EXPECTED_ROLES = {"Bybit": "primary", "Binance": "secondary", "LBank": "tertiary"}
ALLOWED_CATEGORIES = {"spot", "perpetual", "futures"}
ALLOWED_TIMEFRAMES = {"minute15", "hour1", "hour4"}
ALLOWED_SOURCE_STATUS = {"compatible", "unavailable", "incompatible"}
SYMBOL_RE = re.compile(r"^[A-Z0-9]+/[A-Z0-9]+$")


class SourceContractValidationError(ValueError):
    pass


class StrictSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(loader: StrictSafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise SourceContractValidationError("mapping keys must be scalar and hashable") from exc
        if duplicate:
            raise SourceContractValidationError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SourceContractValidationError(f"{path} must be a string-keyed mapping")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing or unknown:
        raise SourceContractValidationError(
            f"{path} schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _bounded_string(value: Any, path: str, max_length: int = 256) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise SourceContractValidationError(f"{path} must be a non-empty string <= {max_length} chars")
    return value


def _utc_timestamp(value: Any, path: str, *, nullable: bool = False) -> datetime | None:
    if value is None and nullable:
        return None
    text = _bounded_string(value, path, 64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SourceContractValidationError(f"{path} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise SourceContractValidationError(f"{path} must be UTC")
    return parsed


def _assert_parser_version() -> None:
    try:
        major = int(str(yaml.__version__).split(".", 1)[0])
    except (AttributeError, TypeError, ValueError) as exc:
        raise SourceContractValidationError("unrecognized PyYAML version") from exc
    if major != SUPPORTED_PYYAML_MAJOR:
        raise SourceContractValidationError(
            f"unsupported PyYAML major version {major}; revalidate parser semantics before use"
        )


def _preflight_yaml(raw: bytes) -> None:
    _assert_parser_version()
    documents = 0
    try:
        for event in yaml.parse(raw, Loader=yaml.SafeLoader):
            if isinstance(event, DocumentStartEvent):
                documents += 1
                if documents > 1:
                    raise SourceContractValidationError("multiple YAML documents are prohibited")
            if isinstance(event, AliasEvent):
                raise SourceContractValidationError("YAML aliases are prohibited")
            if isinstance(event, (CollectionStartEvent, ScalarEvent)):
                if event.anchor is not None:
                    raise SourceContractValidationError("YAML anchors are prohibited")
                if event.tag is not None and not event.tag.startswith("tag:yaml.org,2002:"):
                    raise SourceContractValidationError("custom YAML tags are prohibited")
    except yaml.YAMLError as exc:
        raise SourceContractValidationError(f"invalid YAML: {exc}") from exc
    if documents != 1:
        raise SourceContractValidationError("registry must contain exactly one YAML document")


def validate_source_registry(payload: Any) -> None:
    root = _mapping(payload, "registry")
    _exact_keys(root, ROOT_KEYS, "registry")
    expected_root = {
        "registry_version": "1.0.0",
        "status": "proposed",
        "scope": "research_and_paper_trading_only",
        "issue": 131,
        "adr": "docs/architecture/ADR-009-market-data-source-hierarchy.md",
    }
    for key, expected in expected_root.items():
        if root[key] != expected:
            raise SourceContractValidationError(f"{key} must equal {expected!r}")

    authority = _mapping(root["authority"], "authority")
    _exact_keys(authority, AUTHORITY_KEYS, "authority")
    for key, expected in EXPECTED_AUTHORITY.items():
        if authority[key] != expected:
            raise SourceContractValidationError(f"authority.{key} must equal {expected!r}")

    mappings = root["mappings"]
    if not isinstance(mappings, list):
        raise SourceContractValidationError("mappings must be a list")
    if len(mappings) > MAX_MAPPINGS:
        raise SourceContractValidationError(f"mappings exceeds {MAX_MAPPINGS}-entry limit")

    mapping_ids: set[str] = set()
    for index, raw_mapping in enumerate(mappings):
        path = f"mappings[{index}]"
        mapping = _mapping(raw_mapping, path)
        _exact_keys(mapping, MAPPING_KEYS, path)

        mapping_id = _bounded_string(mapping["mapping_id"], f"{path}.mapping_id", 128)
        if mapping_id in mapping_ids:
            raise SourceContractValidationError(f"duplicate mapping_id: {mapping_id}")
        mapping_ids.add(mapping_id)

        canonical_symbol = _bounded_string(mapping["canonical_symbol"], f"{path}.canonical_symbol", 64)
        if not SYMBOL_RE.fullmatch(canonical_symbol):
            raise SourceContractValidationError(f"{path}.canonical_symbol must use BASE/QUOTE uppercase form")
        category = mapping["market_category"]
        if category not in ALLOWED_CATEGORIES:
            raise SourceContractValidationError(f"{path}.market_category is unsupported")
        quote_asset = _bounded_string(mapping["quote_asset"], f"{path}.quote_asset", 32)
        settlement_asset = _bounded_string(mapping["settlement_asset"], f"{path}.settlement_asset", 32)
        if canonical_symbol.split("/", 1)[1] != quote_asset:
            raise SourceContractValidationError(f"{path}.quote_asset must match canonical symbol quote")
        if mapping["timeframe"] not in ALLOWED_TIMEFRAMES:
            raise SourceContractValidationError(f"{path}.timeframe is unsupported")
        if mapping["timestamp_convention"] != "open_time_utc":
            raise SourceContractValidationError(f"{path}.timestamp_convention must be 'open_time_utc'")
        if mapping["candle_finality"] != "closed_only":
            raise SourceContractValidationError(f"{path}.candle_finality must be 'closed_only'")
        start = _utc_timestamp(mapping["listing_start_utc"], f"{path}.listing_start_utc")
        end = _utc_timestamp(mapping["listing_end_utc"], f"{path}.listing_end_utc", nullable=True)
        if end is not None and start is not None and end < start:
            raise SourceContractValidationError(f"{path}.listing_end_utc precedes listing_start_utc")
        _bounded_string(mapping["volume_semantics"], f"{path}.volume_semantics", 128)
        if mapping["mapping_policy_version"] != "1.0.0":
            raise SourceContractValidationError(f"{path}.mapping_policy_version must be '1.0.0'")
        _bounded_string(settlement_asset, f"{path}.settlement_asset", 32)

        sources = mapping["sources"]
        if not isinstance(sources, list) or not sources:
            raise SourceContractValidationError(f"{path}.sources must be a non-empty list")
        exchanges: set[str] = set()
        bybit_present = False
        for source_index, raw_source in enumerate(sources):
            source_path = f"{path}.sources[{source_index}]"
            source = _mapping(raw_source, source_path)
            _exact_keys(source, SOURCE_KEYS, source_path)
            exchange = source["exchange"]
            if exchange not in EXPECTED_ROLES:
                raise SourceContractValidationError(f"{source_path}.exchange is unsupported")
            if exchange in exchanges:
                raise SourceContractValidationError(f"{path}.sources contains duplicate exchange {exchange}")
            exchanges.add(exchange)
            if source["role"] != EXPECTED_ROLES[exchange]:
                raise SourceContractValidationError(f"{source_path}.role does not match source hierarchy")
            source_symbol = _bounded_string(source["symbol"], f"{source_path}.symbol", 64)
            source_category = source["category"]
            if source_category not in ALLOWED_CATEGORIES:
                raise SourceContractValidationError(f"{source_path}.category is unsupported")
            _bounded_string(source["endpoint_contract"], f"{source_path}.endpoint_contract", 512)
            status = source["status"]
            if status not in ALLOWED_SOURCE_STATUS:
                raise SourceContractValidationError(f"{source_path}.status is unsupported")
            if status == "compatible" and source_category != category:
                raise SourceContractValidationError(f"{source_path} compatible category must match mapping category")
            if status == "compatible" and not source_symbol.strip():
                raise SourceContractValidationError(f"{source_path}.symbol is required for compatible source")
            if exchange == "Bybit":
                bybit_present = True
        if not bybit_present:
            raise SourceContractValidationError(f"{path}.sources must include Bybit primary evidence")


def load_and_validate(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise SourceContractValidationError("registry path must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_REGISTRY_BYTES:
        raise SourceContractValidationError(f"registry exceeds {MAX_REGISTRY_BYTES}-byte limit")
    _preflight_yaml(raw)
    try:
        payload = yaml.load(raw, Loader=StrictSafeLoader)
    except SourceContractValidationError:
        raise
    except yaml.YAMLError as exc:
        raise SourceContractValidationError(f"invalid YAML: {exc}") from exc
    validate_source_registry(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate NEXUS market-data source mapping policy")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("docs/architecture/market-data-source-registry.yaml"),
    )
    args = parser.parse_args()
    try:
        load_and_validate(args.path)
    except (OSError, SourceContractValidationError) as exc:
        parser.exit(1, f"NEXUS market-data source validation failed: {exc}\n")
    print("NEXUS market-data source registry: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
