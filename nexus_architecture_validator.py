from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from yaml.events import AliasEvent, CollectionStartEvent, DocumentStartEvent, ScalarEvent

MAX_REGISTRY_BYTES = 256_000
SUPPORTED_PYYAML_MAJOR = 6

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

ROOT_KEYS = {"registry_version", "status", "scope", "issue", "rules", "modules", "ai_authority", "change_control"}
RULE_KEYS = {
    "dependency_direction",
    "unknown_protected_contract_fields",
    "persisted_accounting_numeric_type",
    "persisted_timestamp_timezone",
    "live_execution",
    "private_credentials",
    "llm_final_authority",
    "failed_candidate_replaces_previous_valid",
}
AI_KEYS = {"allowed", "prohibited", "required_trace"}
CHANGE_CONTROL_KEYS = {"breaking_contract_change_requires", "bug_fix_requires", "done_requires"}
MODULE_KEYS = {
    "market_core": {"contract_version", "owns", "accepts", "emits", "may_depend_on", "must_not_depend_on", "failure_mode"},
    "crypto_adapter": {"contract_version", "owns", "accepts", "emits", "may_depend_on", "must_not_emit", "failure_mode"},
    "forex_adapter": {"contract_version", "owns", "accepts", "emits", "may_depend_on", "must_not_emit", "failure_mode"},
    "research_lab": {"contract_version", "owns", "accepts", "emits", "promotion_authority", "failure_mode"},
    "strategy_lab": {"contract_version", "owns", "accepts", "emits", "promotion_path", "forbidden_promotion", "failure_mode"},
    "regime_detector": {"contract_version", "accepts", "emits", "authority", "failure_mode"},
    "decision_engine": {"contract_version", "accepts", "emits", "required_trace", "authority", "must_not_bypass"},
    "deterministic_risk_engine": {"contract_version", "accepts", "emits", "final_authority_for", "reject_on", "llm_override"},
    "paper_execution": {"contract_version", "invariant", "accepts", "emits", "supports", "prohibited_fields", "failure_mode"},
    "portfolio_event_store": {"contract_version", "owns", "accepts", "emits", "reject_on", "failure_mode"},
    "dashboard_api_adapter": {"contract_version", "accepts", "emits", "may_depend_on", "must_not_directly_mutate", "exposure_constraints", "external_blockers"},
}


class ContractValidationError(ValueError):
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
            raise ContractValidationError("mapping keys must be scalar and hashable") from exc
        if duplicate:
            raise ContractValidationError(f"duplicate YAML key: {key!r}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{path} must be a string-keyed mapping")
    return value


def _exact_keys(mapping: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(mapping)
    unknown = set(mapping) - expected
    if missing or unknown:
        raise ContractValidationError(
            f"{path} schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _string_set(value: Any, path: str) -> set[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) for item in value):
        raise ContractValidationError(f"{path} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise ContractValidationError(f"{path} contains duplicates")
    return set(value)


def _assert_parser_version() -> None:
    try:
        major = int(str(yaml.__version__).split(".", 1)[0])
    except (AttributeError, TypeError, ValueError) as exc:
        raise ContractValidationError("unrecognized PyYAML version") from exc
    if major != SUPPORTED_PYYAML_MAJOR:
        raise ContractValidationError(
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
                    raise ContractValidationError("multiple YAML documents are prohibited")
            if isinstance(event, AliasEvent):
                raise ContractValidationError("YAML aliases are prohibited")
            if isinstance(event, (CollectionStartEvent, ScalarEvent)):
                if event.anchor is not None:
                    raise ContractValidationError("YAML anchors are prohibited")
                if event.tag is not None and not event.tag.startswith("tag:yaml.org,2002:"):
                    raise ContractValidationError("custom YAML tags are prohibited")
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"invalid YAML: {exc}") from exc
    if documents != 1:
        raise ContractValidationError("registry must contain exactly one YAML document")


def validate_contract_registry(payload: Any) -> None:
    root = _mapping(payload, "registry")
    _exact_keys(root, ROOT_KEYS, "registry")
    if root["registry_version"] != "1.0.0":
        raise ContractValidationError("unsupported registry_version")
    if root["scope"] != "research_and_paper_trading_only":
        raise ContractValidationError("scope must remain research_and_paper_trading_only")

    rules = _mapping(root["rules"], "rules")
    _exact_keys(rules, RULE_KEYS, "rules")
    expected_rules = {
        "live_execution": "prohibited",
        "private_credentials": "prohibited",
        "llm_final_authority": "prohibited",
        "failed_candidate_replaces_previous_valid": False,
    }
    for key, expected in expected_rules.items():
        if rules[key] != expected:
            raise ContractValidationError(f"rules.{key} must equal {expected!r}")

    modules = _mapping(root["modules"], "modules")
    missing = REQUIRED_MODULES - set(modules)
    unknown = set(modules) - REQUIRED_MODULES
    if missing:
        raise ContractValidationError(f"missing required modules: {sorted(missing)}")
    if unknown:
        raise ContractValidationError(f"unknown protected modules: {sorted(unknown)}")

    for name, raw_contract in modules.items():
        contract = _mapping(raw_contract, f"modules.{name}")
        _exact_keys(contract, MODULE_KEYS[name], f"modules.{name}")
        if contract["contract_version"] != "1.0.0":
            raise ContractValidationError(f"modules.{name}.contract_version must be 1.0.0")
        if "failure_mode" in MODULE_KEYS[name] and not isinstance(contract["failure_mode"], str):
            raise ContractValidationError(f"modules.{name}.failure_mode is required")

    market_core = modules["market_core"]
    required_core_blocks = {
        "crypto_adapter", "forex_adapter", "dashboard_api_adapter", "llm_or_agent_client", "exchange_or_broker_sdk"
    }
    if not required_core_blocks <= _string_set(market_core["must_not_depend_on"], "modules.market_core.must_not_depend_on"):
        raise ContractValidationError("market_core dependency denylist is incomplete")

    risk = modules["deterministic_risk_engine"]
    if risk["llm_override"] != "prohibited":
        raise ContractValidationError("deterministic risk authority must not be overridden")
    required_rejections = {"unknown", "malformed", "stale", "duplicate", "reordered", "unsupported"}
    if not required_rejections <= _string_set(risk["reject_on"], "modules.deterministic_risk_engine.reject_on"):
        raise ContractValidationError("risk fail-closed rejection set is incomplete")

    paper = modules["paper_execution"]
    invariant = _mapping(paper["invariant"], "modules.paper_execution.invariant")
    _exact_keys(invariant, {"paper_trading_only"}, "modules.paper_execution.invariant")
    if invariant["paper_trading_only"] is not True:
        raise ContractValidationError("paper_execution must be paper_trading_only")
    if not PROHIBITED_PAPER_FIELDS <= _string_set(paper["prohibited_fields"], "modules.paper_execution.prohibited_fields"):
        raise ContractValidationError("paper_execution prohibited field set is incomplete")

    dashboard = modules["dashboard_api_adapter"]
    required_mutation_blocks = {"portfolio_event_store", "paper_execution", "deterministic_risk_engine"}
    if not required_mutation_blocks <= _string_set(dashboard["must_not_directly_mutate"], "modules.dashboard_api_adapter.must_not_directly_mutate"):
        raise ContractValidationError("dashboard mutation denylist is incomplete")

    ai = _mapping(root["ai_authority"], "ai_authority")
    _exact_keys(ai, AI_KEYS, "ai_authority")
    required_ai_blocks = {
        "authorize_final_trading_decision", "change_risk_policy", "create_or_use_financial_credentials",
        "place_real_order", "request_withdrawal", "promote_strategy_directly_to_live",
    }
    if not required_ai_blocks <= _string_set(ai["prohibited"], "ai_authority.prohibited"):
        raise ContractValidationError("AI authority denylist is incomplete")

    change_control = _mapping(root["change_control"], "change_control")
    _exact_keys(change_control, CHANGE_CONTROL_KEYS, "change_control")
    if not REQUIRED_CHANGE_GATES <= _string_set(change_control["breaking_contract_change_requires"], "change_control.breaking_contract_change_requires"):
        raise ContractValidationError("breaking-change gates are incomplete")
    if "regression_test" not in _string_set(change_control["bug_fix_requires"], "change_control.bug_fix_requires"):
        raise ContractValidationError("bug fixes must require regression evidence")


def load_and_validate(path: Path) -> None:
    if not path.is_file() or path.is_symlink():
        raise ContractValidationError("registry path must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_REGISTRY_BYTES:
        raise ContractValidationError(f"registry exceeds {MAX_REGISTRY_BYTES}-byte limit")
    _preflight_yaml(raw)
    try:
        payload = yaml.load(raw, Loader=StrictSafeLoader)
    except ContractValidationError:
        raise
    except yaml.YAMLError as exc:
        raise ContractValidationError(f"invalid YAML: {exc}") from exc
    validate_contract_registry(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the NEXUS module contract registry")
    parser.add_argument("path", nargs="?", type=Path, default=Path("docs/architecture/module-contract-registry.yaml"))
    args = parser.parse_args()
    try:
        load_and_validate(args.path)
    except (OSError, ContractValidationError) as exc:
        parser.exit(1, f"NEXUS architecture validation failed: {exc}\n")
    print("NEXUS architecture contract registry: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
