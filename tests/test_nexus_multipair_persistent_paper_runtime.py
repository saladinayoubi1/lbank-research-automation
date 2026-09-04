from __future__ import annotations

from copy import deepcopy

import nexus_multipair_persistent_paper_runtime as runtime


SOURCE_SHA = "a" * 40


def _loop_snapshot(*, fresh: int) -> dict:
    all_cells = [
        f"{symbol}:{timeframe}"
        for symbol in runtime.EXPECTED_SYMBOLS
        for timeframe in runtime.EXPECTED_TIMEFRAMES
    ]
    active = fresh == runtime.EXPECTED_CELLS
    core = {
        "schema_version": runtime.legacy_loop.SCHEMA,
        "source_sha": SOURCE_SHA,
        "run_id": "123",
        "now_ms": 1_788_540_000_000,
        "status": "PAPER_LOOP_ACTIVE" if active else "WAITING_FOR_FRESH_CELLS",
        "data_mode": runtime.public_regime.PUBLIC_DATA_MODE,
        "matrix_snapshot_digest": "b" * 64,
        "expected_cell_count": runtime.EXPECTED_CELLS,
        "fresh_cell_count": fresh,
        "fresh_cells": all_cells[:fresh],
        "expected_lane_count": runtime.EXPECTED_LANES,
        "regime_status": "VERIFIED" if active else "WAITING_FOR_FRESH_CELLS",
        "regime_cycle_digest": "c" * 64 if active else None,
        "maintenance_digest": "d" * 64 if active else None,
        "performance_refresh_digest": "e" * 64 if active else None,
        "performance_health_feedback_operational": active,
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": "bounded_research",
        "strategy_discovery_ready_stage_count": 7,
        "strategy_research_required": active,
        "strategy_discovery_health_trigger_requested": active,
        "strategy_discovery_health_trigger_contract": "successful_paper_loop_new_4h_boundary_only",
        "strategy_discovery_rotation": "automatic_daily_and_health_driven_bounded_rotation",
        "persistent_state_digest": "f" * 64,
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": active,
        "regime_selected_exposure_increase_operational": active,
        "remaining_core_gap": (
            "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF"
            if active
            else "WAITING_FOR_FRESH_CELLS"
        ),
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "loop_digest": runtime.legacy_loop._digest(core)}


def _regime_snapshot() -> dict:
    cells = []
    for symbol in runtime.EXPECTED_SYMBOLS:
        for timeframe in runtime.EXPECTED_TIMEFRAMES:
            core = {
                "schema_version": runtime.demo_regime.CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": SOURCE_SHA,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
            }
            cells.append({**core, "cell_digest": runtime.demo_regime._digest(core)})
    core = {
        "schema_version": runtime.demo_regime.SCHEMA,
        "matrix_id": "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2",
        "source_sha": SOURCE_SHA,
        "archive_sha256": None,
        "data_mode": runtime.public_regime.PUBLIC_DATA_MODE,
        "context_digests": {symbol: "1" * 64 for symbol in runtime.EXPECTED_SYMBOLS},
        "expected_cell_count": runtime.EXPECTED_CELLS,
        "verified_cell_count": runtime.EXPECTED_CELLS,
        "cells": cells,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "frozen_prospective_hour4_lane_mutated": False,
    }
    return {**core, "cycle_digest": runtime.demo_regime._digest(core)}


def test_v2_loop_verifier_requires_exact_12_cell_36_lane_surface() -> None:
    waiting = _loop_snapshot(fresh=11)
    assert runtime.verify_loop_snapshot_v2(waiting)["decision"] == "pass"

    active = _loop_snapshot(fresh=12)
    assert runtime.verify_loop_snapshot_v2(active)["decision"] == "pass"

    legacy_shape = deepcopy(active)
    legacy_shape["expected_cell_count"] = 6
    legacy_shape["expected_lane_count"] = 18
    unsigned = dict(legacy_shape)
    unsigned.pop("loop_digest")
    legacy_shape["loop_digest"] = runtime.legacy_loop._digest(unsigned)
    assert runtime.verify_loop_snapshot_v2(legacy_shape)["decision"] == "reject"


def test_v2_regime_verifier_requires_all_four_symbols_and_three_timeframes() -> None:
    value = _regime_snapshot()
    assert runtime.verify_regime_cycle_v2(value)["decision"] == "pass"

    missing = deepcopy(value)
    missing["cells"] = missing["cells"][:-1]
    missing["verified_cell_count"] = 11
    missing["expected_cell_count"] = 11
    unsigned = dict(missing)
    unsigned.pop("cycle_digest")
    missing["cycle_digest"] = runtime.demo_regime._digest(unsigned)
    assert runtime.verify_regime_cycle_v2(missing)["decision"] == "reject"


def test_v2_regime_scope_restores_all_legacy_verifiers() -> None:
    original_demo = runtime.demo_regime.verify_cycle_snapshot
    original_public = runtime.public_regime.verify_cycle_snapshot
    original_validate = runtime.rebalance._validate_regime_snapshot
    original_rebalance = runtime.rebalance.verify_regime_selected_rebalance
    original_increase = runtime.exposure_increase.verify_regime_selected_exposure_increase

    with runtime._v2_regime_verifier_scope():
        assert runtime.demo_regime.verify_cycle_snapshot is runtime.verify_regime_cycle_v2
        assert runtime.public_regime.verify_cycle_snapshot is runtime.verify_regime_cycle_v2
        assert runtime.rebalance._validate_regime_snapshot is runtime._validate_regime_snapshot_v2
        assert runtime.rebalance.verify_regime_selected_rebalance is runtime.verify_rebalance_v2
        assert (
            runtime.exposure_increase.verify_regime_selected_exposure_increase
            is runtime.verify_exposure_increase_v2
        )

    assert runtime.demo_regime.verify_cycle_snapshot is original_demo
    assert runtime.public_regime.verify_cycle_snapshot is original_public
    assert runtime.rebalance._validate_regime_snapshot is original_validate
    assert runtime.rebalance.verify_regime_selected_rebalance is original_rebalance
    assert runtime.exposure_increase.verify_regime_selected_exposure_increase is original_increase


def test_v2_manifest_surface_constants_match_phase8_acceptance() -> None:
    assert runtime.EXPECTED_SYMBOLS == ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
    assert runtime.EXPECTED_TIMEFRAMES == ("minute15", "hour1", "hour4")
    assert runtime.EXPECTED_FAMILIES == ("momentum", "trend_breakout", "mean_reversion")
    assert runtime.EXPECTED_CELLS == 12
    assert runtime.EXPECTED_LANES == 36
