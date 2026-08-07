from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import nexus_architecture_validator as validator
from nexus_architecture_validator import ContractValidationError, load_and_validate, validate_contract_registry

REGISTRY = Path("docs/architecture/module-contract-registry.yaml")


def valid_payload() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def write_candidate(tmp_path: Path, text: str) -> Path:
    candidate = tmp_path / "registry.yaml"
    candidate.write_text(text, encoding="utf-8")
    return candidate


def test_current_registry_is_valid() -> None:
    load_and_validate(REGISTRY)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p.__setitem__("status", "accepted"), "status"),
        (lambda p: p.__setitem__("issue", 95), "issue"),
        (lambda p: p["rules"].__setitem__("dependency_direction", "bidirectional"), "dependency_direction"),
        (lambda p: p["rules"].__setitem__("unknown_protected_contract_fields", "allow"), "unknown_protected_contract_fields"),
        (lambda p: p["rules"].__setitem__("persisted_accounting_numeric_type", "float"), "persisted_accounting_numeric_type"),
        (lambda p: p["rules"].__setitem__("persisted_timestamp_timezone", "local"), "persisted_timestamp_timezone"),
        (lambda p: p["rules"].__setitem__("live_execution", "allowed"), "live_execution"),
        (lambda p: p["rules"].__setitem__("private_credentials", "allowed"), "private_credentials"),
        (lambda p: p["modules"]["paper_execution"]["invariant"].__setitem__("paper_trading_only", False), "paper_trading_only"),
        (lambda p: p["modules"]["deterministic_risk_engine"].__setitem__("llm_override", "allowed"), "risk authority"),
        (lambda p: p["modules"]["dashboard_api_adapter"]["must_not_directly_mutate"].remove("portfolio_event_store"), "dashboard mutation"),
        (lambda p: p["ai_authority"]["prohibited"].remove("place_real_order"), "AI authority"),
        (lambda p: p["change_control"]["bug_fix_requires"].remove("regression_test"), "bug_fix_requires"),
    ],
)
def test_safety_mutations_fail_closed(mutate, message: str) -> None:
    payload = deepcopy(valid_payload())
    mutate(payload)
    with pytest.raises(ContractValidationError, match=message):
        validate_contract_registry(payload)


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("rules",),
        ("modules", "market_core"),
        ("modules", "paper_execution", "invariant"),
        ("ai_authority",),
        ("change_control",),
    ],
)
def test_unknown_or_shadow_fields_fail_closed(path: tuple[str, ...]) -> None:
    payload = deepcopy(valid_payload())
    target = payload
    for segment in path:
        target = target[segment]
    target["live_executon"] = "prohibited"
    with pytest.raises(ContractValidationError, match="schema mismatch"):
        validate_contract_registry(payload)


def test_unknown_protected_module_fails_closed() -> None:
    payload = deepcopy(valid_payload())
    payload["modules"]["live_execution"] = {"contract_version": "1.0.0", "failure_mode": "none"}
    with pytest.raises(ContractValidationError, match="unknown protected modules"):
        validate_contract_registry(payload)


def test_missing_required_module_fails_closed() -> None:
    payload = deepcopy(valid_payload())
    del payload["modules"]["market_core"]
    with pytest.raises(ContractValidationError, match="missing required modules"):
        validate_contract_registry(payload)


def test_duplicate_policy_entry_fails_closed() -> None:
    payload = deepcopy(valid_payload())
    payload["modules"]["paper_execution"]["prohibited_fields"].append("credential")
    with pytest.raises(ContractValidationError, match="contains duplicates"):
        validate_contract_registry(payload)


@pytest.mark.parametrize(
    "text",
    [
        "registry_version: 1.0.0\nregistry_version: 1.0.0\n",
        "rules:\n  live_execution: prohibited\n  live_execution: allowed\n",
    ],
)
def test_duplicate_yaml_keys_fail_closed(tmp_path: Path, text: str) -> None:
    with pytest.raises(ContractValidationError, match="duplicate YAML key"):
        load_and_validate(write_candidate(tmp_path, text))


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("base: &policy\n  live_execution: prohibited\nrules: *policy\n", "anchors|aliases"),
        ("---\na: 1\n---\nb: 2\n", "multiple YAML documents"),
        ("registry_version: !unsafe 1.0.0\n", "custom YAML tags"),
    ],
)
def test_special_yaml_structures_fail_closed(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ContractValidationError, match=message):
        load_and_validate(write_candidate(tmp_path, text))


def test_parser_major_version_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validator.yaml, "__version__", "7.0.0")
    with pytest.raises(ContractValidationError, match="revalidate parser semantics"):
        load_and_validate(REGISTRY)


def test_malformed_yaml_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ContractValidationError, match="invalid YAML"):
        load_and_validate(write_candidate(tmp_path, "modules: [\n"))


def test_oversized_registry_fails_closed(tmp_path: Path) -> None:
    candidate = tmp_path / "registry.yaml"
    candidate.write_bytes(b"x" * 256_001)
    with pytest.raises(ContractValidationError, match="byte limit"):
        load_and_validate(candidate)


def test_symlink_registry_fails_closed(tmp_path: Path) -> None:
    source = tmp_path / "source.yaml"
    source.write_text(REGISTRY.read_text(encoding="utf-8"), encoding="utf-8")
    candidate = tmp_path / "registry.yaml"
    try:
        candidate.symlink_to(source)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")
    with pytest.raises(ContractValidationError, match="non-symlink"):
        load_and_validate(candidate)
