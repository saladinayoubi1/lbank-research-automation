from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from nexus_system_map_validator import (
    SystemMapValidationError,
    load_system_map,
    validate_pr_precheck,
    validate_system_map,
)

SYSTEM_MAP = Path("config/nexus-system-map-v1.yaml")


def valid_payload() -> dict:
    return yaml.safe_load(SYSTEM_MAP.read_text(encoding="utf-8"))


def valid_pr_body() -> str:
    return """## NEXUS architecture precheck
- **System Map nodes**: SYS-00, OBS-80
- **Existing component**: NEXUS architecture validation layer
- **Duplicate-work check**: Extends the existing architecture validator; no parallel authority path
- **Primary executor / lane**: GitHub-hosted CI
- **Upstream dependencies**: Master System Map and accepted ADRs
- **Downstream consumers**: Pull requests and main-branch verification
- **Authority / Paper-Live boundary**: CI validation only; Live=false; no Paper execution authority
- **Data provenance**: Repository-owned configuration only
- **Failure mode / rollback**: Fail closed; revert the validator/workflow commit
- **Tests / independent QA**: Unit regression tests plus PR workflow gate
- **Deployment impact**: CI only; no owner runtime mutation
- **DONE evidence**: Exact-head green System Map Gate
"""


def test_current_system_map_is_valid() -> None:
    load_system_map(SYSTEM_MAP)


def test_only_laptop_1_may_be_paper_writer() -> None:
    payload = deepcopy(valid_payload())
    payload["machines"]["laptop_2"]["paper_writer"] = True
    with pytest.raises(SystemMapValidationError, match="paper_writer"):
        validate_system_map(payload)


def test_live_trading_cannot_be_enabled() -> None:
    payload = deepcopy(valid_payload())
    payload["invariants"]["live_trading"] = True
    with pytest.raises(SystemMapValidationError, match="live_trading"):
        validate_system_map(payload)


@pytest.mark.parametrize("runner", ["NEXUS-LOCAL-FAILOVER", "NEXUS-BYBIT-FAILOVER"])
def test_runtime_failovers_cannot_become_always_on(runner: str) -> None:
    payload = deepcopy(valid_payload())
    payload["runners"][runner]["state_policy"] = "active"
    with pytest.raises(SystemMapValidationError, match=runner):
        validate_system_map(payload)


def test_research_primary_cannot_move_to_runtime_laptop_silently() -> None:
    payload = deepcopy(valid_payload())
    payload["runners"]["NEXUS-RESEARCH-RUNNER"]["machine"] = "laptop_1"
    with pytest.raises(SystemMapValidationError, match="NEXUS-RESEARCH-RUNNER"):
        validate_system_map(payload)


@pytest.mark.parametrize("source", ["bybit", "binance", "lbank", "bitget"])
def test_market_sources_cannot_be_silently_substituted(source: str) -> None:
    payload = deepcopy(valid_payload())
    payload["sources"][source]["substitution_allowed"] = True
    with pytest.raises(SystemMapValidationError, match="substitution_allowed"):
        validate_system_map(payload)


def test_required_flow_cannot_skip_independent_qa() -> None:
    payload = deepcopy(valid_payload())
    payload["required_flow"].remove("QA-41")
    with pytest.raises(SystemMapValidationError, match="required_flow"):
        validate_system_map(payload)


def test_required_flow_cannot_move_paper_before_risk() -> None:
    payload = deepcopy(valid_payload())
    flow = payload["required_flow"]
    risk_index = flow.index("RISK-61")
    paper_index = flow.index("PAPER-62")
    flow[risk_index], flow[paper_index] = flow[paper_index], flow[risk_index]
    with pytest.raises(SystemMapValidationError, match="required_flow"):
        validate_system_map(payload)


def test_protective_exit_cannot_gain_open_authority() -> None:
    payload = deepcopy(valid_payload())
    payload["nodes"]["SAFE-64"]["authority"].append("open")
    with pytest.raises(SystemMapValidationError, match="Protective Exit authority"):
        validate_system_map(payload)


def test_validation_cannot_become_candidate_selector() -> None:
    payload = deepcopy(valid_payload())
    payload["invariants"]["validation_selects_candidates"] = True
    with pytest.raises(SystemMapValidationError, match="validation_selects_candidates"):
        validate_system_map(payload)


def test_arbitrary_minimum_trade_gate_cannot_be_reintroduced() -> None:
    payload = deepcopy(valid_payload())
    payload["invariants"]["arbitrary_minimum_trade_count_gate"] = True
    with pytest.raises(SystemMapValidationError, match="arbitrary_minimum_trade_count_gate"):
        validate_system_map(payload)


def test_change_precheck_contract_cannot_drop_duplicate_work_check() -> None:
    payload = deepcopy(valid_payload())
    payload["change_precheck_required"].remove("duplicate_work_check")
    with pytest.raises(SystemMapValidationError, match="change_precheck_required"):
        validate_system_map(payload)


def test_valid_pr_architecture_precheck_is_accepted() -> None:
    validate_pr_precheck(valid_pr_body(), valid_payload())


def test_pr_precheck_rejects_unknown_node() -> None:
    body = valid_pr_body().replace("SYS-00, OBS-80", "SYS-00, FAKE-99")
    with pytest.raises(SystemMapValidationError, match="unknown System Map nodes"):
        validate_pr_precheck(body, valid_payload())


def test_pr_precheck_rejects_missing_field() -> None:
    body = valid_pr_body().replace(
        "- **Duplicate-work check**: Extends the existing architecture validator; no parallel authority path\n",
        "",
    )
    with pytest.raises(SystemMapValidationError, match="Duplicate-work check"):
        validate_pr_precheck(body, valid_payload())


def test_pr_precheck_requires_explicit_live_boundary() -> None:
    body = valid_pr_body().replace(
        "CI validation only; Live=false; no Paper execution authority",
        "CI validation only; no execution authority",
    )
    with pytest.raises(SystemMapValidationError, match="Live=false"):
        validate_pr_precheck(body, valid_payload())
