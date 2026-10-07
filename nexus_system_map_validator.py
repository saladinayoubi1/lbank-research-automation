from __future__ import annotations

import argparse
import os
import re
from pathlib import Path
from typing import Any

import yaml

from nexus_architecture_validator import ContractValidationError, StrictSafeLoader, _preflight_yaml

MAX_SYSTEM_MAP_BYTES = 256_000

ROOT_KEYS = {
    "version",
    "date",
    "scope",
    "baseline_main_sha",
    "invariants",
    "machines",
    "runners",
    "sources",
    "nodes",
    "required_flow",
    "forbidden_shortcuts",
    "change_precheck_required",
}

EXPECTED_INVARIANTS = {
    "live_trading": False,
    "paper_reference_balance_usdt": 500,
    "primary_market_identity": "bybit",
    "github_source_of_truth": True,
    "github_is_runtime_database": False,
    "paper_single_writer": True,
    "independent_qa_before_qualification": True,
    "qualification_before_demo": True,
    "training_selects_candidates": True,
    "validation_selects_candidates": False,
    "arbitrary_minimum_trade_count_gate": False,
}

EXPECTED_MACHINES = {
    "laptop_1": {
        "hostname": "DESKTOP-1R1081M",
        "role": "runtime_paper_primary",
        "paper_writer": True,
        "live_trading": False,
    },
    "laptop_2": {
        "hostname": "DESKTOP-F4SA4VL",
        "role": "research_primary_conditional_failover",
        "paper_writer": False,
        "live_trading": False,
    },
}

EXPECTED_RUNNERS = {
    "NEXUS-LOCAL-RUNNER": ("laptop_1", "active", "owner_local_runtime"),
    "NEXUS-BYBIT-WSL": ("laptop_1", "active", "bybit_network_primary"),
    "NEXUS-WINDOWS-DR": ("laptop_1", "active", "windows_disaster_recovery"),
    "NEXUS-RESEARCH-RUNNER": ("laptop_2", "active", "research_primary"),
    "NEXUS-RESEARCH-FAILOVER": ("laptop_1", "watchdog_only", "research_failover"),
    "NEXUS-LOCAL-FAILOVER": ("laptop_2", "watchdog_only", "local_runtime_failover"),
    "NEXUS-BYBIT-FAILOVER": ("laptop_2", "watchdog_only", "bybit_network_failover"),
    "NEXUS-RESEARCH-SECONDARY": ("laptop_2", "disabled", "retired_secondary_registration"),
}

EXPECTED_SOURCES = {
    "bybit": "primary_market_and_paper_identity",
    "binance": "secondary_corroboration",
    "lbank": "tertiary_research_only",
    "bitget": "auxiliary_research_only",
}

EXPECTED_NODES = {
    "SYS-00",
    "CTRL-10",
    "CTRL-11",
    "CTRL-12",
    "DATA-20",
    "DATA-21",
    "RES-30",
    "RES-31",
    "RES-32",
    "VAL-40",
    "QA-41",
    "QUAL-42",
    "REG-50",
    "RUNTIME-60",
    "RISK-61",
    "PAPER-62",
    "PAPER-63",
    "SAFE-64",
    "UI-70",
    "UI-71",
    "OBS-80",
    "REL-90",
}

EXPECTED_FLOW = [
    "DATA-20",
    "DATA-21",
    "RES-30",
    "RES-31",
    "RES-32",
    "VAL-40",
    "QA-41",
    "QUAL-42",
    "REG-50",
    "RUNTIME-60",
    "RISK-61",
    "PAPER-62",
    "PAPER-63",
]

REQUIRED_SHORTCUT_BLOCKS = {
    "research_to_paper_without_qa",
    "validation_used_to_select_training_winner",
    "ui_direct_event_store_mutation",
    "ai_risk_override",
    "backup_source_relabelled_as_bybit",
    "multiple_owner_paper_writers",
    "always_on_failover_beside_healthy_primary",
    "live_trading_authority",
}

EXPECTED_CHANGE_PRECHECK = {
    "system_map_nodes",
    "existing_component",
    "duplicate_work_check",
    "primary_executor",
    "upstream_dependencies",
    "downstream_consumers",
    "authority_level",
    "data_provenance",
    "failure_mode",
    "rollback",
    "tests",
    "qa_requirement",
    "deployment_impact",
    "done_evidence",
}

PR_FIELDS = (
    "System Map nodes",
    "Existing component",
    "Duplicate-work check",
    "Primary executor / lane",
    "Upstream dependencies",
    "Downstream consumers",
    "Authority / Paper-Live boundary",
    "Data provenance",
    "Failure mode / rollback",
    "Tests / independent QA",
    "Deployment impact",
    "DONE evidence",
)


class SystemMapValidationError(ContractValidationError):
    pass


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SystemMapValidationError(f"{path} must be a string-keyed mapping")
    return value


def _exact_keys(mapping: dict[str, Any], expected: set[str], path: str) -> None:
    missing = expected - set(mapping)
    unknown = set(mapping) - expected
    if missing or unknown:
        raise SystemMapValidationError(
            f"{path} schema mismatch; missing={sorted(missing)}, unknown={sorted(unknown)}"
        )


def _unique_string_list(value: Any, path: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not isinstance(item, str) or not item for item in value):
        raise SystemMapValidationError(f"{path} must be a non-empty string list")
    if len(value) != len(set(value)):
        raise SystemMapValidationError(f"{path} contains duplicates")
    return value


def validate_system_map(payload: Any) -> None:
    root = _mapping(payload, "system_map")
    _exact_keys(root, ROOT_KEYS, "system_map")

    if root["version"] != "nexus-system-map/v1":
        raise SystemMapValidationError("version must equal 'nexus-system-map/v1'")
    if root["scope"] != "research_and_paper_only":
        raise SystemMapValidationError("scope must remain research_and_paper_only")
    if not isinstance(root["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", root["date"]):
        raise SystemMapValidationError("date must be an ISO YYYY-MM-DD string")
    if not isinstance(root["baseline_main_sha"], str) or not re.fullmatch(r"[0-9a-f]{40}", root["baseline_main_sha"]):
        raise SystemMapValidationError("baseline_main_sha must be a lowercase 40-character commit SHA")

    invariants = _mapping(root["invariants"], "invariants")
    _exact_keys(invariants, set(EXPECTED_INVARIANTS), "invariants")
    for key, expected in EXPECTED_INVARIANTS.items():
        if invariants[key] != expected:
            raise SystemMapValidationError(f"invariants.{key} must equal {expected!r}")

    machines = _mapping(root["machines"], "machines")
    _exact_keys(machines, set(EXPECTED_MACHINES), "machines")
    paper_writers: list[str] = []
    for machine_name, expected in EXPECTED_MACHINES.items():
        machine = _mapping(machines[machine_name], f"machines.{machine_name}")
        _exact_keys(
            machine,
            {"hostname", "role", "paper_writer", "live_trading", "responsibilities"},
            f"machines.{machine_name}",
        )
        for key, value in expected.items():
            if machine[key] != value:
                raise SystemMapValidationError(
                    f"machines.{machine_name}.{key} must equal {value!r}"
                )
        _unique_string_list(machine["responsibilities"], f"machines.{machine_name}.responsibilities")
        if machine["paper_writer"] is True:
            paper_writers.append(machine_name)
    if paper_writers != ["laptop_1"]:
        raise SystemMapValidationError("exactly laptop_1 must be the owner Paper writer")

    runners = _mapping(root["runners"], "runners")
    _exact_keys(runners, set(EXPECTED_RUNNERS), "runners")
    for runner_name, (machine_name, state_policy, role) in EXPECTED_RUNNERS.items():
        runner = _mapping(runners[runner_name], f"runners.{runner_name}")
        _exact_keys(runner, {"machine", "state_policy", "role"}, f"runners.{runner_name}")
        expected = {"machine": machine_name, "state_policy": state_policy, "role": role}
        for key, value in expected.items():
            if runner[key] != value:
                raise SystemMapValidationError(
                    f"runners.{runner_name}.{key} must equal {value!r}"
                )

    sources = _mapping(root["sources"], "sources")
    _exact_keys(sources, set(EXPECTED_SOURCES), "sources")
    for source_name, authority in EXPECTED_SOURCES.items():
        source = _mapping(sources[source_name], f"sources.{source_name}")
        _exact_keys(source, {"authority", "substitution_allowed"}, f"sources.{source_name}")
        if source["authority"] != authority:
            raise SystemMapValidationError(
                f"sources.{source_name}.authority must equal {authority!r}"
            )
        if source["substitution_allowed"] is not False:
            raise SystemMapValidationError(
                f"sources.{source_name}.substitution_allowed must remain false"
            )

    nodes = _mapping(root["nodes"], "nodes")
    _exact_keys(nodes, EXPECTED_NODES, "nodes")
    for node_id, raw_node in nodes.items():
        _mapping(raw_node, f"nodes.{node_id}")

    for node_id in ("RES-30", "RES-31", "RES-32"):
        if nodes[node_id].get("primary_executor") != "NEXUS-RESEARCH-RUNNER":
            raise SystemMapValidationError(
                f"nodes.{node_id}.primary_executor must be NEXUS-RESEARCH-RUNNER"
            )
    for node_id in ("RUNTIME-60", "RISK-61", "PAPER-62", "PAPER-63", "SAFE-64", "UI-70"):
        if nodes[node_id].get("primary_machine") != "laptop_1":
            raise SystemMapValidationError(f"nodes.{node_id}.primary_machine must be laptop_1")
    if nodes["PAPER-62"].get("single_writer") is not True:
        raise SystemMapValidationError("nodes.PAPER-62.single_writer must remain true")

    guard = nodes["SAFE-64"]
    if set(_unique_string_list(guard.get("authority"), "nodes.SAFE-64.authority")) != {"reduce", "close"}:
        raise SystemMapValidationError("Protective Exit authority must be exactly reduce and close")
    forbidden_guard = set(_unique_string_list(guard.get("forbidden"), "nodes.SAFE-64.forbidden"))
    if forbidden_guard != {"open", "reverse", "increase_exposure", "live"}:
        raise SystemMapValidationError("Protective Exit forbidden authority set changed")

    flow = _unique_string_list(root["required_flow"], "required_flow")
    if flow != EXPECTED_FLOW:
        raise SystemMapValidationError(
            "required_flow must preserve Data -> Research -> Validation -> QA -> Qualification -> Risk -> Paper ordering"
        )

    shortcut_blocks = set(_unique_string_list(root["forbidden_shortcuts"], "forbidden_shortcuts"))
    if shortcut_blocks != REQUIRED_SHORTCUT_BLOCKS:
        raise SystemMapValidationError("forbidden_shortcuts must match the protected shortcut denylist")

    change_precheck = set(_unique_string_list(root["change_precheck_required"], "change_precheck_required"))
    if change_precheck != EXPECTED_CHANGE_PRECHECK:
        raise SystemMapValidationError("change_precheck_required must match the protected precheck set")


def load_system_map(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SystemMapValidationError("system map path must be a regular non-symlink file")
    raw = path.read_bytes()
    if len(raw) > MAX_SYSTEM_MAP_BYTES:
        raise SystemMapValidationError(f"system map exceeds {MAX_SYSTEM_MAP_BYTES}-byte limit")
    _preflight_yaml(raw)
    try:
        payload = yaml.load(raw, Loader=StrictSafeLoader)
    except ContractValidationError:
        raise
    except yaml.YAMLError as exc:
        raise SystemMapValidationError(f"invalid YAML: {exc}") from exc
    validate_system_map(payload)
    return payload


def _extract_pr_field(body: str, label: str) -> str:
    pattern = re.compile(
        rf"(?mi)^\s*[-*]?\s*\*\*{re.escape(label)}\*\*:\s*(.*?)\s*$"
    )
    match = pattern.search(body)
    if not match:
        raise SystemMapValidationError(f"PR precheck field missing: {label}")
    value = match.group(1).strip()
    if not value or value.startswith("<") or value.lower() in {"n/a", "na", "todo", "tbd"}:
        raise SystemMapValidationError(f"PR precheck field is empty/placeholder: {label}")
    return value


def validate_pr_precheck(body: str, system_map: dict[str, Any]) -> None:
    if not isinstance(body, str) or not body.strip():
        raise SystemMapValidationError("PR body is required for NEXUS System Map precheck")

    values = {label: _extract_pr_field(body, label) for label in PR_FIELDS}
    node_tokens = set(re.findall(r"\b[A-Z]+-\d{2}\b", values["System Map nodes"]))
    if not node_tokens:
        raise SystemMapValidationError("System Map nodes must name at least one node ID")
    unknown_nodes = node_tokens - set(system_map["nodes"])
    if unknown_nodes:
        raise SystemMapValidationError(f"PR references unknown System Map nodes: {sorted(unknown_nodes)}")

    boundary = values["Authority / Paper-Live boundary"].lower()
    if "live=false" not in boundary.replace(" ", "") and "live trading disabled" not in boundary:
        raise SystemMapValidationError(
            "Authority / Paper-Live boundary must explicitly state Live=false or Live trading disabled"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the NEXUS master system map and optional PR precheck")
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path("config/nexus-system-map-v1.yaml"),
    )
    parser.add_argument(
        "--pr-body-env",
        help="Environment variable containing a pull-request body to validate against the system map",
    )
    args = parser.parse_args()
    try:
        payload = load_system_map(args.path)
        if args.pr_body_env:
            validate_pr_precheck(os.environ.get(args.pr_body_env, ""), payload)
    except (OSError, ContractValidationError) as exc:
        parser.exit(1, f"NEXUS system-map validation failed: {exc}\n")
    print("NEXUS master system map: valid")
    if args.pr_body_env:
        print("NEXUS PR architecture precheck: valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
