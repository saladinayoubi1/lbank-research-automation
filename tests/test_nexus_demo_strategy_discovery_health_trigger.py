from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_demo_strategy_discovery_health_trigger as trigger_module
from nexus_demo_strategy_discovery_health_trigger import (
    DemoStrategyDiscoveryHealthTriggerError,
    build_demo_health_trigger,
    verify_demo_health_trigger,
)


SOURCE_SHA = "a" * 40
CYCLE_DIGEST = "b" * 64
LIFECYCLE_DIGEST = "c" * 64


def _regime(*, candidates=0, drift="STABLE", cash="1.000000"):
    cells = [
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "candidate_count": candidates,
            "drift_state": drift,
            "cash_weight": cash,
        }
        for symbol in ("BTCUSDT", "ETHUSDT")
        for timeframe in ("minute15", "hour1", "hour4")
    ]
    return {
        "source_sha": SOURCE_SHA,
        "cycle_digest": CYCLE_DIGEST,
        "expected_cell_count": 6,
        "verified_cell_count": 6,
        "cells": cells,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def _lifecycle():
    return {
        "source_sha": SOURCE_SHA,
        "regime_cycle_digest": CYCLE_DIGEST,
        "lifecycle_digest": LIFECYCLE_DIGEST,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "regime_selected_rebalance_operational": True,
    }


@pytest.fixture(autouse=True)
def _verified_inputs(monkeypatch):
    monkeypatch.setattr(trigger_module, "verify_cycle_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        trigger_module, "verify_demo_regime_lifecycle", lambda _value: {"decision": "pass"}
    )


def test_zero_eligible_candidates_requests_bounded_research():
    decision = build_demo_health_trigger(_regime(), _lifecycle())
    assert decision["should_dispatch"] is True
    assert decision["reason_code"] == "NO_ELIGIBLE_PAPER_CANDIDATES"
    assert decision["eligible_candidate_count"] == 0
    assert decision["all_cash_cell_count"] == 6
    assert decision["qualification_authority"] is False
    assert decision["automatic_strategy_promotion"] is False
    assert verify_demo_health_trigger(decision)["decision"] == "pass"


def test_performance_drift_requests_research_even_with_candidates():
    decision = build_demo_health_trigger(
        _regime(candidates=1, drift="ACTION_REQUIRED", cash="0.500000"), _lifecycle()
    )
    assert decision["should_dispatch"] is True
    assert decision["reason_code"] == "PERFORMANCE_DRIFT_RESEARCH_REQUIRED"
    assert decision["eligible_candidate_count"] == 6
    assert decision["action_required_cell_count"] == 6


def test_healthy_candidates_do_not_duplicate_health_dispatch():
    decision = build_demo_health_trigger(_regime(candidates=1, cash="0.500000"), _lifecycle())
    assert decision["should_dispatch"] is False
    assert decision["reason_code"] == "CURRENT_DEMO_RESEARCH_HEALTH_SUFFICIENT"
    assert decision["daily_rotation_remains_required"] is True


def test_source_or_cycle_substitution_fails_closed():
    lifecycle = _lifecycle()
    lifecycle["source_sha"] = "d" * 40
    with pytest.raises(DemoStrategyDiscoveryHealthTriggerError):
        build_demo_health_trigger(_regime(), lifecycle)

    lifecycle = _lifecycle()
    lifecycle["regime_cycle_digest"] = "e" * 64
    with pytest.raises(DemoStrategyDiscoveryHealthTriggerError):
        build_demo_health_trigger(_regime(), lifecycle)


def test_trigger_tamper_is_rejected_even_after_rehash():
    decision = build_demo_health_trigger(_regime(), _lifecycle())
    forged = deepcopy(decision)
    forged["qualification_authority"] = True
    core = dict(forged)
    core.pop("trigger_digest")
    forged["trigger_digest"] = trigger_module._digest(core)
    assert verify_demo_health_trigger(forged)["decision"] == "reject"
