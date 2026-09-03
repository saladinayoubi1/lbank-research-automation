from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import market_data_source_validator as validator
from market_data_source_validator import SourceContractValidationError, load_and_validate, validate_source_registry

REGISTRY = Path("docs/architecture/market-data-source-registry.yaml")


def current_payload() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def valid_mapping() -> dict:
    return {
        "mapping_id": "btc-usdt-spot-minute15-v1",
        "canonical_symbol": "BTC/USDT",
        "market_category": "spot",
        "quote_asset": "USDT",
        "settlement_asset": "USDT",
        "timeframe": "minute15",
        "manifest_timeframe": "15m",
        "timestamp_convention": "open_time_utc",
        "timestamp_grid_ms": 900000,
        "candle_finality": "closed_only",
        "listing_start_utc": "2024-01-01T00:00:00Z",
        "listing_end_utc": None,
        "volume_semantics": "base_asset_volume",
        "mapping_policy_version": "1.0.0",
        "sources": [
            {
                "exchange": "Bybit",
                "role": "primary",
                "symbol": "BTCUSDT",
                "category": "spot",
                "interval": "15",
                "endpoint_contract": "public-kline-v1",
                "status": "compatible",
            },
            {
                "exchange": "Binance",
                "role": "secondary",
                "symbol": "BTCUSDT",
                "category": "spot",
                "market": "spot",
                "interval": "15m",
                "endpoint_contract": "public-klines-v1",
                "status": "compatible",
            },
            {
                "exchange": "LBank",
                "role": "tertiary",
                "symbol": "btc_usdt",
                "category": "spot",
                "endpoint_contract": "public-kline-v1",
                "status": "incompatible",
            },
        ],
    }


def payload_with_mapping() -> dict:
    payload = current_payload()
    payload["mappings"] = [valid_mapping()]
    return payload


def write_candidate(tmp_path: Path, text: str) -> Path:
    candidate = tmp_path / "registry.yaml"
    candidate.write_text(text, encoding="utf-8")
    return candidate


def test_current_registry_is_valid_and_authorizes_reviewed_four_symbol_spot_mappings() -> None:
    payload = current_payload()
    mappings = payload["mappings"]
    assert payload["registry_version"] == "1.2.0"
    assert len(mappings) == 12
    assert {item["canonical_symbol"] for item in mappings} == {
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT"
    }
    assert {item["timeframe"] for item in mappings} == {"minute15", "hour1", "hour4"}
    assert all(item["market_category"] == "spot" for item in mappings)
    assert all(item["candle_finality"] == "closed_only" for item in mappings)
    assert all([source["exchange"] for source in item["sources"]] == ["Bybit", "Binance", "LBank"] for item in mappings)
    assert all([source["role"] for source in item["sources"]] == ["primary", "secondary", "tertiary"] for item in mappings)
    for symbol in ("SOL/USDT", "XRP/USDT"):
        rows = [item for item in mappings if item["canonical_symbol"] == symbol]
        assert len(rows) == 3
        assert {row["timeframe"] for row in rows} == {"minute15", "hour1", "hour4"}
        assert all(row["sources"][0]["exchange"] == "Bybit" for row in rows)
        assert all(row["sources"][0]["status"] == "compatible" for row in rows)
    load_and_validate(REGISTRY)


def test_explicit_compatible_mapping_passes() -> None:
    validate_source_registry(payload_with_mapping())


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["authority"].__setitem__("primary", "Binance"), "authority.primary"),
        (lambda p: p["authority"].__setitem__("silent_cross_exchange_substitution", "allowed"), "silent_cross_exchange_substitution"),
        (lambda p: p["authority"].__setitem__("live_trading", "allowed"), "live_trading"),
        (lambda p: p["authority"].__setitem__("private_credentials", "allowed"), "private_credentials"),
        (lambda p: p["authority"].__setitem__("unknown_mapping", "allow"), "unknown_mapping"),
        (lambda p: p["authority"].__setitem__("failed_candidate_replaces_previous_valid", True), "failed_candidate"),
        (lambda p: p["semantic_binding"].__setitem__("unknown_or_missing_mapping", "allow"), "unknown_or_missing_mapping"),
        (lambda p: p["semantic_binding"].__setitem__("caller_supplied_semantics_authoritative", True), "caller_supplied_semantics_authoritative"),
        (lambda p: p["mappings"][0].__setitem__("canonical_symbol", "btc_usdt"), "BASE/QUOTE"),
        (lambda p: p["mappings"][0].__setitem__("timeframe", "5m"), "timeframe"),
        (lambda p: p["mappings"][0].__setitem__("manifest_timeframe", "1h"), "manifest_timeframe"),
        (lambda p: p["mappings"][0].__setitem__("timestamp_grid_ms", 3600000), "timestamp_grid_ms"),
        (lambda p: p["mappings"][0].__setitem__("candle_finality", "open_allowed"), "candle_finality"),
        (lambda p: p["mappings"][0]["sources"][0].__setitem__("interval", "60"), "interval"),
        (lambda p: p["mappings"][0]["sources"][1].__setitem__("market", "perpetual"), "market"),
        (lambda p: p["mappings"][0]["sources"][1].__setitem__("interval", "1h"), "interval"),
        (lambda p: p["mappings"][0]["sources"][1].__setitem__("role", "primary"), "source hierarchy"),
        (lambda p: p["mappings"][0]["sources"][1].__setitem__("category", "perpetual"), "compatible category"),
    ],
)
def test_policy_and_mapping_mutations_fail_closed(mutate, message: str) -> None:
    payload = payload_with_mapping()
    mutate(payload)
    with pytest.raises(SourceContractValidationError, match=message):
        validate_source_registry(payload)


def test_unknown_field_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"][0]["silent_fallback"] = True
    with pytest.raises(SourceContractValidationError, match="schema mismatch"):
        validate_source_registry(payload)


def test_missing_semantic_dimension_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["semantic_binding"]["required_dimensions"].remove("timestamp_grid_ms")
    with pytest.raises(SourceContractValidationError, match="required_dimensions"):
        validate_source_registry(payload)


def test_duplicate_mapping_id_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"].append(deepcopy(payload["mappings"][0]))
    with pytest.raises(SourceContractValidationError, match="duplicate mapping_id"):
        validate_source_registry(payload)


def test_duplicate_exchange_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"][0]["sources"].append(deepcopy(payload["mappings"][0]["sources"][1]))
    with pytest.raises(SourceContractValidationError, match="duplicate exchange"):
        validate_source_registry(payload)


def test_missing_bybit_primary_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"][0]["sources"] = [payload["mappings"][0]["sources"][1]]
    with pytest.raises(SourceContractValidationError, match="Bybit primary"):
        validate_source_registry(payload)


def test_listing_window_reversal_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"][0]["listing_end_utc"] = "2023-12-31T23:59:00Z"
    with pytest.raises(SourceContractValidationError, match="precedes"):
        validate_source_registry(payload)


def test_non_utc_listing_timestamp_fails_closed() -> None:
    payload = payload_with_mapping()
    payload["mappings"][0]["listing_start_utc"] = "2024-01-01T00:00:00+03:30"
    with pytest.raises(SourceContractValidationError, match="must be UTC"):
        validate_source_registry(payload)


@pytest.mark.parametrize(
    "text",
    [
        "registry_version: 1.2.0\nregistry_version: 1.2.0\n",
        "authority:\n  primary: Bybit\n  primary: Binance\n",
    ],
)
def test_duplicate_yaml_keys_fail_closed(tmp_path: Path, text: str) -> None:
    with pytest.raises(SourceContractValidationError, match="duplicate YAML key"):
        load_and_validate(write_candidate(tmp_path, text))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("base: &policy\n  primary: Bybit\nauthority: *policy\n", "anchors|aliases"),
        ("---\na: 1\n---\nb: 2\n", "multiple YAML documents"),
        ("registry_version: !unsafe 1.2.0\n", "custom YAML tags"),
    ],
)
def test_special_yaml_structures_fail_closed(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(SourceContractValidationError, match=message):
        load_and_validate(write_candidate(tmp_path, text))


def test_parser_major_version_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validator.yaml, "__version__", "7.0.0")
    with pytest.raises(SourceContractValidationError, match="revalidate parser semantics"):
        load_and_validate(REGISTRY)


def test_oversized_registry_fails_closed(tmp_path: Path) -> None:
    candidate = tmp_path / "registry.yaml"
    candidate.write_bytes(b"x" * 128_001)
    with pytest.raises(SourceContractValidationError, match="byte limit"):
        load_and_validate(candidate)


def test_symlink_registry_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    candidate = tmp_path / "registry.yaml"
    try:
        candidate.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(SourceContractValidationError, match="non-symlink"):
        load_and_validate(candidate)
