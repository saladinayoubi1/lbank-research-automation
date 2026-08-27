from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from nexus_isolated_product_runtime import IsolatedProductRuntime
from nexus_regime_selected_position_rebalance import (
    ACTION_SCHEMA,
    CELL_SCHEMA,
    SCHEMA,
    _digest,
    _position,
    _risk_reducing_transition,
    verify_regime_selected_rebalance,
)
from paper_event_store import replay


SOURCE_SHA = "a" * 40
AS_OF_MS = 1_787_875_200_000  # 2026-08-28T00:00:00Z


def _runtime_with_position(tmp_path: Path) -> IsolatedProductRuntime:
    runtime = IsolatedProductRuntime(
        tmp_path / "runtime",
        account_id="nexus-regime-demo:btcusdt:hour4:momentum",
        clock=lambda: "2026-08-28T00:00:00Z",
    )
    opened = runtime.submit_paper_order({
        "operation": "open",
        "symbol": "BTCUSDT",
        "timeframe": "hour4",
        "side": "long",
        "quantity": "1",
        "reference_price": "100",
        "stop_price": "98",
        "target_price": "103",
    })
    assert opened["accepted"] is True
    return runtime


def test_risk_reducing_transition_reduces_then_closes_without_exposure_increase(
    tmp_path: Path,
) -> None:
    runtime = _runtime_with_position(tmp_path)

    reduced = _risk_reducing_transition(
        runtime=runtime,
        source_sha=SOURCE_SHA,
        cell_digest="b" * 64,
        selection_digest="c" * 64,
        symbol="BTCUSDT",
        timeframe="hour4",
        family="momentum",
        strategy_version="1.0.0",
        as_of_ms=AS_OF_MS,
        reference_price="100",
        target_quantity=__import__("decimal").Decimal("0.5"),
    )
    assert reduced["action"] == "REDUCED"
    assert reduced["pre_quantity"] == "1"
    assert reduced["post_quantity"] == "0.5"
    assert reduced["risk_reason"] == "risk_reducing_exit"
    assert reduced["exposure_increased"] is False
    with runtime._lock:
        state = replay(runtime._ensure_account()).state
    assert _position(state, "BTCUSDT")[1] == __import__("decimal").Decimal("0.5")

    closed = _risk_reducing_transition(
        runtime=runtime,
        source_sha=SOURCE_SHA,
        cell_digest="d" * 64,
        selection_digest="e" * 64,
        symbol="BTCUSDT",
        timeframe="hour4",
        family="momentum",
        strategy_version="1.0.0",
        as_of_ms=AS_OF_MS,
        reference_price="100",
        target_quantity=__import__("decimal").Decimal("0"),
    )
    assert closed["action"] == "CLOSED"
    assert closed["post_quantity"] == "0"
    assert closed["exposure_increased"] is False
    with runtime._lock:
        state = replay(runtime._ensure_account()).state
    assert _position(state, "BTCUSDT") is None


def test_increase_request_holds_until_fresh_deterministic_risk_path(tmp_path: Path) -> None:
    runtime = _runtime_with_position(tmp_path)
    result = _risk_reducing_transition(
        runtime=runtime,
        source_sha=SOURCE_SHA,
        cell_digest="b" * 64,
        selection_digest="c" * 64,
        symbol="BTCUSDT",
        timeframe="hour4",
        family="momentum",
        strategy_version="1.0.0",
        as_of_ms=AS_OF_MS,
        reference_price="100",
        target_quantity=__import__("decimal").Decimal("1.5"),
    )
    assert result["action"] == "HOLD_INCREASE_PENDING_FRESH_RISK"
    assert result["pre_quantity"] == "1"
    assert result["post_quantity"] == "1"
    assert result["event_count_added"] == 0
    assert result["exposure_increased"] is False


def _verified_snapshot() -> dict:
    cells = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for timeframe in ("minute15", "hour1", "hour4"):
            action_core = {
                "schema_version": ACTION_SCHEMA,
                "family": "momentum",
                "action": "HELD",
                "reason_code": "TARGET_MATCHES_CURRENT_EXPOSURE",
                "target_quantity": "1",
                "pre_quantity": "1",
                "post_quantity": "1",
                "event_count_added": 0,
                "risk_reason": None,
                "terminal_event_digest": "1" * 64,
                "paper_only": True,
                "live_trading_authority": False,
                "exposure_increased": False,
            }
            action = {**action_core, "action_digest": _digest(action_core)}
            cell_core = {
                "schema_version": CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": SOURCE_SHA,
                "as_of_ms": AS_OF_MS,
                "regime_cell_digest": "2" * 64,
                "runtime_digest": "3" * 64,
                "runtime_verification_digest": "4" * 64,
                "original_selection_digest": "5" * 64,
                "corrected_selection_digest": "6" * 64,
                "corrected_cash_weight": "0.500000",
                "corrected_allocations": [],
                "action_count": 1,
                "actions": [action],
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
                "exposure_increased": False,
            }
            cells.append({**cell_core, "cell_rebalance_digest": _digest(cell_core)})
    core = {
        "schema_version": SCHEMA,
        "source_sha": SOURCE_SHA,
        "regime_cycle_digest": "7" * 64,
        "cell_count": 6,
        "cells": cells,
        "held_count": 6,
        "reduced_count": 0,
        "closed_count": 0,
        "increase_pending_count": 0,
        "risk_reducing_rebalance_operational": True,
        "exposure_increase_operational": False,
        "regime_selected_rebalance_operational": False,
        "remaining_core_gap": "REGIME_SELECTED_EXPOSURE_INCREASE_WITH_FRESH_RISK",
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "exposure_increased": False,
    }
    return {**core, "rebalance_digest": _digest(core)}


def test_rebalance_verifier_rejects_tamper_or_fake_completion() -> None:
    snapshot = _verified_snapshot()
    assert verify_regime_selected_rebalance(snapshot)["decision"] == "pass"

    tampered = deepcopy(snapshot)
    tampered["cells"][0]["actions"][0]["post_quantity"] = "2"
    unsigned = dict(tampered)
    unsigned.pop("rebalance_digest")
    tampered["rebalance_digest"] = _digest(unsigned)
    assert verify_regime_selected_rebalance(tampered)["decision"] == "reject"

    fabricated = deepcopy(snapshot)
    fabricated["regime_selected_rebalance_operational"] = True
    fabricated["remaining_core_gap"] = None
    unsigned = dict(fabricated)
    unsigned.pop("rebalance_digest")
    fabricated["rebalance_digest"] = _digest(unsigned)
    assert verify_regime_selected_rebalance(fabricated)["decision"] == "reject"
