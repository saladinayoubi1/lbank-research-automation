from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from nexus_architecture_validator import ContractValidationError, load_and_validate, validate_contract_registry

REGISTRY = Path("docs/architecture/module-contract-registry.yaml")


def valid_payload() -> dict:
    return yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))


def test_current_registry_is_valid() -> None:
    load_and_validate(REGISTRY)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["rules"].__setitem__("live_execution", "allowed"), "live_execution"),
        (lambda p: p["rules"].__setitem__("private_credentials", "allowed"), "private_credentials"),
        (
            lambda p: p["modules"]["paper_execution"]["invariant"].__setitem__("paper_trading_only", False),
            "paper_trading_only",
        ),
        (
            lambda p: p["modules"]["deterministic_risk_engine"].__setitem__("llm_override", "allowed"),
            "risk authority",
        ),
        (
            lambda p: p["modules"]["dashboard_api_adapter"]["must_not_directly_mutate"].remove(
                "portfolio_event_store"
            ),
            "dashboard mutation",
        ),
        (
            lambda p: p["ai_authority"]["prohibited"].remove("place_real_order"),
            "AI authority",
        ),
        (
            lambda p: p["change_control"]["bug_fix_requires"].remove("regression_test"),
            "regression",
        ),
    ],
)
def test_safety_mutations_fail_closed(mutate, message: str) -> None:
    payload = deepcopy(valid_payload())
    mutate(payload)
    with pytest.raises(ContractValidationError, match=message):
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


def test_malformed_yaml_fails_closed(tmp_path: Path) -> None:
    candidate = tmp_path / "registry.yaml"
    candidate.write_text("modules: [\n", encoding="utf-8")
    with pytest.raises(ContractValidationError, match="invalid YAML"):
        load_and_validate(candidate)


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
