from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import nexus_regime_selected_exposure_increase as increase
from nexus_isolated_product_runtime import IsolatedProductRuntime
from paper_event_store import replay
from product_runtime import _risk_policy, _risk_state


SOURCE_SHA = "a" * 40
AS_OF_MS = 1_787_875_200_000
OCCURRED = "2026-08-28T00:00:00Z"


def _runtime_with_position(tmp_path: Path) -> IsolatedProductRuntime:
    runtime = IsolatedProductRuntime(
        tmp_path / "runtime",
        account_id="nexus-regime-demo:btcusdt:hour4:momentum",
        clock=lambda: OCCURRED,
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


def _research() -> SimpleNamespace:
    return SimpleNamespace(
        _last_research={
            "dataset": {"last_close": "100"},
            "qualification": {"strategy_version": "1.0.0"},
        }
    )


def _preparation(*, blocked: bool = False):
    def build(_research, *, portfolio_state_override, signals_today_override):
        policy = _risk_policy()
        policy["eligible_strategies"] = [{"id": "momentum", "version": "1.0.0"}]
        policy["max_signal_age_seconds"] = 60_000
        if blocked:
            policy["max_position_fraction"] = "0.0001"
        lane = {
            "family": "momentum",
            "dataset": {
                "dataset_id": "canonical:bybit-test",
                "dataset_revision": "1" * 64,
                "source_id": "Bybit",
                "source_timestamp": OCCURRED,
                "received_timestamp": OCCURRED,
                "symbol": "BTCUSDT",
                "timeframe": "hour4",
                "readiness_status": "ready",
                "provenance_digest": "2" * 64,
            },
            "qualification": {
                "artifact_id": "experiment-1",
                "artifact_digest": "3" * 64,
                "strategy_id": "momentum",
                "strategy_version": "1.0.0",
                "dataset_id": "canonical:bybit-test",
                "dataset_revision": "1" * 64,
                "status": "paper_eligible",
                "qualified_at": OCCURRED,
            },
            "regime": {
                "regime_id": "regime:test:aligned-up",
                "regime_version": "product-regime-v1",
                "label": "trend",
                "confidence": "1",
                "source_timestamp": OCCURRED,
                "dataset_id": "canonical:bybit-test",
                "dataset_revision": "1" * 64,
                "symbol": "BTCUSDT",
                "timeframe": "hour4",
            },
            "decision": {
                "decision_id": "proposal:base",
                "operation": "open",
                "side": "long",
                "quantity": "2",
                "reference_price": "100",
                "stop_price": "98",
                "target_price": "103",
                "confidence": "1",
                "strategy_id": "momentum",
                "strategy_version": "1.0.0",
                "dataset_id": "canonical:bybit-test",
                "dataset_revision": "1" * 64,
                "regime_id": "regime:test:aligned-up",
                "regime_version": "product-regime-v1",
                "symbol": "BTCUSDT",
                "timeframe": "hour4",
                "source_timestamp": OCCURRED,
                "correlation_id": "proposal:base",
                "causation_id": "regime:test:aligned-up",
                "risk_policy_version": "1.0.0",
            },
            "risk_state": _risk_state(
                portfolio_state_override,
                symbol="BTCUSDT",
                signals_today=signals_today_override,
            ),
            "risk_policy": policy,
            "portfolio_state": portfolio_state_override,
            "fee_rate": "0.001",
            "slippage_bps": "5",
        }
        return {"status": "ready", "lane": lane}
    return build


def _call(runtime, monkeypatch, *, blocked: bool = False):
    with runtime._lock:
        before = replay(runtime._ensure_account()).state
    monkeypatch.setattr(increase, "prepare_regime_paper_lane", _preparation(blocked=blocked))
    return before, increase._atomic_fresh_risk_increase(
        runtime=runtime,
        research_runtime=_research(),
        source_sha=SOURCE_SHA,
        symbol="BTCUSDT",
        timeframe="hour4",
        family="momentum",
        as_of_ms=AS_OF_MS,
        cell_digest="4" * 64,
        rebalance_cell_digest="5" * 64,
        corrected_selection_digest="6" * 64,
        allocation_weight=Decimal("0.75"),
        expected_pre_quantity=Decimal("1"),
        expected_head_digest=before.last_event_digest,
    )


def test_atomic_increase_commits_close_and_open_only_after_fresh_risk(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = _runtime_with_position(tmp_path)
    before, result = _call(runtime, monkeypatch)

    assert result["status"] == "INCREASED_WITH_FRESH_RISK"
    assert result["initial_quantity"] == "1"
    assert result["final_quantity"] == "1.50"
    assert result["open_risk_allowed"] is True
    assert result["risk_replay_verified"] is True
    assert result["journal_committed"] is True
    assert result["unauthorized_exposure_increase"] is False
    with runtime._lock:
        after = replay(runtime._ensure_account()).state
    position = increase._position(after, "BTCUSDT")
    assert position is not None and position[1] == Decimal("1.50")
    assert after.last_event_digest == result["terminal_event_digest"]
    assert after.last_event_digest != before.last_event_digest


def test_fresh_risk_rejection_preserves_original_position_and_journal(
    monkeypatch, tmp_path: Path
) -> None:
    runtime = _runtime_with_position(tmp_path)
    before, result = _call(runtime, monkeypatch, blocked=True)

    assert result["status"] == "INCREASE_BLOCKED_BY_DETERMINISTIC_RISK"
    assert result["open_risk_allowed"] is False
    assert result["risk_replay_verified"] is True
    assert result["journal_committed"] is False
    with runtime._lock:
        after = replay(runtime._ensure_account()).state
    position = increase._position(after, "BTCUSDT")
    assert position is not None and position[1] == Decimal("1")
    assert after.last_event_digest == before.last_event_digest


def _verified_snapshot() -> dict:
    cells = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        for timeframe in ("minute15", "hour1", "hour4"):
            cell_core = {
                "schema_version": increase.CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": SOURCE_SHA,
                "regime_cell_digest": "1" * 64,
                "rebalance_cell_digest": "2" * 64,
                "corrected_selection_digest": "3" * 64,
                "pending_count": 0,
                "action_count": 0,
                "actions": [],
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
                "unauthorized_exposure_increase": False,
            }
            cells.append({
                **cell_core,
                "cell_increase_digest": increase._digest(cell_core),
            })
    core = {
        "schema_version": increase.SCHEMA,
        "source_sha": SOURCE_SHA,
        "regime_cycle_digest": "4" * 64,
        "rebalance_digest": "5" * 64,
        "cell_count": 6,
        "cells": cells,
        "pending_count": 0,
        "increased_count": 0,
        "risk_blocked_count": 0,
        "no_increase_count": 0,
        "exposure_increase_operational": True,
        "fresh_deterministic_risk_required": True,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "unauthorized_exposure_increase": False,
    }
    return {**core, "increase_digest": increase._digest(core)}


def test_increase_verifier_rejects_authority_or_digest_tamper() -> None:
    snapshot = _verified_snapshot()
    assert increase.verify_regime_selected_exposure_increase(snapshot)["decision"] == "pass"

    tampered = deepcopy(snapshot)
    tampered["live_trading_authority"] = True
    unsigned = dict(tampered)
    unsigned.pop("increase_digest")
    tampered["increase_digest"] = increase._digest(unsigned)
    assert increase.verify_regime_selected_exposure_increase(tampered)["decision"] == "reject"

    tampered = deepcopy(snapshot)
    tampered["cells"][0]["source_sha"] = "b" * 40
    unsigned = dict(tampered)
    unsigned.pop("increase_digest")
    tampered["increase_digest"] = increase._digest(unsigned)
    assert increase.verify_regime_selected_exposure_increase(tampered)["decision"] == "reject"
