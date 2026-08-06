from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml

REQUIRED_MODULES = {
    "market_core",
    "crypto_adapter",
    "forex_adapter",
    "research_lab",
    "strategy_lab",
    "regime_detector",
    "decision_engine",
    "deterministic_risk_engine",
    "paper_execution",
    "portfolio_event_store",
    "dashboard_api_adapter",
}
PROHIBITED_PAPER_FIELDS = {
    "credential",
    "live_order",
    "withdrawal",
    "production_promotion",
    "billing",
}
REQUIRED_CHANGE_GATES = {
    "ADR",
    "migration_plan",
    "compatibility_window",
    "rollback_plan",
    "recovery_test",
}


class ContractValidationError(ValueError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractValidationError(f"{path} must be a mapping")
    return value


def _string_set(value: Any, path: str) -> set[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ContractValidationError(f"{path} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise ContractValidationError(f"{path} contains duplicates")
    return set(value)


def validate_contract_registry(payload: Any) -> None:
    root = _mapping(payload, "registry")
    if root.get("registry_version") != "1.0.0":
        raise ContractValidationError("unsupported registry_version")
    if root.get("scope") != "research_and_paper_trading_only":
        raise ContractValidationError("scope must remain research_and_paper_trading_only")

    rules = _mapping(root.get("rules"), "rules")
    expected_rules = {
        "live_execution": "prohibited",
        "private_credentials": "prohibited",
        "llm_final_authority": "prohibited",
        "failed_candidate_replaces_previous_valid": False,
    }
    for key, expected in expected_rules.items():
        if rules.get(key) != expected:
            raise ContractValidationError(f"rules.{key} must equal {expected!r}")

    modules = _mapping(root.get("modules"), "modules")
    missing = REQUIRED_MODULES - set(modules)
    if missing:
        raise ContractValidationError(f"missing required modules: {sorted(missing)}")
    unknown = set(modules) - REQUIRED_MODULES
    if unknown:
        raise ContractValidationError(f"unknown protected modules: {sorted(unknown)}")

    for name, raw_contract in modules.items():
        contract = _mapping(raw_contract, f"modules.{name}")
        if contract.get("contract_version") != "1.0.0":
            raise ContractValidationError(f"modules.{name}.contract_version must be 1.0.0")
        if not isinstance(contract.get("failure_mode"), str) and name not in {
            "decision_engine", "deterministic_risk_engine", "dashboard_api_adapter"
        }:
            raise ContractValidationError(f"modules.{name}.failure_mode is required")

    market_core = modules["market_core"]
    forbidden_core_dependencies = _string_set(
        market_core.get("must_not_depend_on"), "modules.market_core.must_not_depend_on"
    )
    required_core_blocks = {
        "crypto_adapter",
        "forex_adapter",
        "dashboard_api_adapter",
        "llm_or_agent_client",
        "exchange_or_broker_sdk",
    }
    if not required_core_blocks <= forbidden_core_dependencies:
        raise ContractValidationError("market_core dependency denylist is incomplete")

    risk = modules["deterministic_risk_engine"]
    if risk.get("llm_override") != "prohibited":
        raise ContractValidationError("deterministic risk authority must not be overridden")
    required_rejections = {"unknown", "malformed", "stale", "duplicate", "reordered", "unsupported"}
    if not required_rejections <= _string_set(risk.get("reject_on"), "modules.deterministic_risk_engine.reject_on"):
        raise ContractValidationError("risk fail-closed rejection set is incomplete")

    paper = modules["paper_execution"]
    invariant = _mapping(paper.get("invariant"), "modules.paper_execution.invariant")
    if invariant.get("paper_trading_only") is not True:
        raise ContractValidationError("paper_execution must be paper_trading_only")
    if not PROHIBITED_PAPER_FIELDS <= _string_set(
        paper.get("prohibited_fields"), "modules.paper_execution.prohibited_fields"
    ):
        raise ContractValidationError("paper_execution prohibited field set is incomplete")

    dashboard = modules["dashboard_api_adapter"]
    required_mutation_blocks = {"portfolio_event_store", "paper_execution", "deterministic_risk_engine"}
    if not required_mutation_blocks <= _string_set(
        dashboard.get("must_not_directly_mutate"), "modules.dashboard_api_adapter.must_not_directly_mutate"
    ):
        raise ContractValidationError("dashboard mutation denylist is incomplete")

    ai = _mapping(root.get("ai_authority"), "ai_authority")
    required_ai_blocks = {
        "authorize_final_trading_decision",
        "change_risk_policy",
        "create_or_use_financial_credentials",
        "place_real_order",
        "request_withdrawal",
        "promote_strategy_directly_to_live",
    }
    if not required_ai_blocks <= _string_set(ai.get("prohibited"), "ai_authority.prohibited"):
        raise ContractValidationError("AI authority denylist is incomplete")

    change_control = _mapping(root.get("change_control"), "change_control")
    if not REQUIRED_CHANGE_GATES <= _string_set(
        change_control.get("breaking_contract_change_requires"),
        "change_control.breaking_contract_change_requires",
    ):
        raise ContractValidationError("breaking-change gates are incomplete")
    if "regression_test" not in _string_set(
        change_control.get("bug_fix_requires"), "change_control.bug_fix_requires"
    ):
        raise ContractValidationError("bug fixes must require regression evidence")


def load_and_validate(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractValidationError("registry path must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > 256_000:
        raise ContractValidationError("registry exceeds 256000-byte limit")
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"invalid YAML: {exc}") from exc
    validate_contract_registry(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the NEXUS module contract registry")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("docs/architecture/module-contract-registry.yaml"),
    )
    args = parser.parse_args()
    try:
        load_and_validate(args.path)
    except (OSError, ContractValidationError) as exc:
        parser.exit(1, f"NEXUS architecture validation failed: {exc}\n")
    print("NEXUS architecture contract registry: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
