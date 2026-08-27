from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_persistent_paper_trading_loop as loop
from nexus_strategy_discovery_health_trigger import (
    StrategyDiscoveryHealthTriggerError,
    build_health_trigger,
    verify_health_trigger,
)


SOURCE_SHA = "a" * 40


def _snapshot(*, regime_status="VERIFIED", research_required=True):
    core = {
        "schema_version": loop.SCHEMA,
        "source_sha": SOURCE_SHA,
        "run_id": "123",
        "now_ms": 1_728_000_000_000,
        "status": "PAPER_LOOP_ACTIVE",
        "data_mode": "public_bybit_closed_candles",
        "matrix_snapshot_digest": "1" * 64,
        "expected_cell_count": 6,
        "fresh_cell_count": 6,
        "fresh_cells": [f"cell-{index}" for index in range(6)],
        "expected_lane_count": 18,
        "regime_status": regime_status,
        "regime_cycle_digest": "2" * 64,
        "maintenance_digest": "3" * 64,
        "performance_refresh_digest": "4" * 64,
        "performance_health_feedback_operational": True,
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": "nexus_multitimeframe_strategy_discovery",
        "strategy_discovery_ready_stage_count": 7,
        "strategy_research_required": research_required,
        "strategy_discovery_health_trigger_requested": bool(
            research_required and regime_status == "VERIFIED"
        ),
        "strategy_discovery_health_trigger_contract": "successful_paper_loop_new_4h_boundary_only",
        "strategy_discovery_rotation": "automatic_daily_and_health_driven_bounded_rotation",
        "persistent_state_digest": "5" * 64,
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": True,
        "regime_selected_exposure_increase_operational": True,
        "remaining_core_gap": "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF",
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "loop_digest": loop._digest(core)}


def test_new_verified_cash_or_unhealthy_boundary_requests_bounded_discovery():
    trigger = build_health_trigger(_snapshot())
    assert trigger["should_dispatch"] is True
    assert trigger["reason_code"] == "NEW_4H_BOUNDARY_RESEARCH_REQUIRED"
    assert trigger["daily_rotation_remains_required"] is True
    assert trigger["qualification_authority"] is False
    assert trigger["automatic_strategy_promotion"] is False
    assert verify_health_trigger(trigger)["decision"] == "pass"


def test_no_new_4h_boundary_does_not_duplicate_health_dispatch():
    trigger = build_health_trigger(_snapshot(regime_status="NO_NEW_4H_BOUNDARY"))
    assert trigger["should_dispatch"] is False
    assert trigger["reason_code"] == "NO_NEW_4H_BOUNDARY"
    assert trigger["daily_rotation_remains_required"] is True


def test_healthy_portfolio_keeps_daily_rotation_without_extra_dispatch():
    trigger = build_health_trigger(_snapshot(research_required=False))
    assert trigger["should_dispatch"] is False
    assert trigger["reason_code"] == "CURRENT_RESEARCH_HEALTH_SUFFICIENT"
    assert trigger["daily_rotation_remains_required"] is True


def test_tampered_loop_authority_or_digest_fails_closed():
    tampered = deepcopy(_snapshot())
    tampered["live_trading_authority"] = True
    with pytest.raises(StrategyDiscoveryHealthTriggerError):
        build_health_trigger(tampered)

    rehashed = deepcopy(_snapshot())
    rehashed["automatic_strategy_promotion"] = True
    unsigned = dict(rehashed)
    unsigned.pop("loop_digest")
    rehashed["loop_digest"] = loop._digest(unsigned)
    with pytest.raises(StrategyDiscoveryHealthTriggerError):
        build_health_trigger(rehashed)


def test_trigger_tamper_is_rejected_even_after_authority_change():
    trigger = build_health_trigger(_snapshot())
    forged = deepcopy(trigger)
    forged["qualification_authority"] = True
    unsigned = dict(forged)
    unsigned.pop("trigger_digest")
    forged["trigger_digest"] = __import__(
        "nexus_strategy_discovery_health_trigger"
    )._digest(unsigned)
    assert verify_health_trigger(forged)["decision"] == "reject"
