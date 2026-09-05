from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import nexus_demo_regime_cycle as legacy_regime
import nexus_multipair_regime_lifecycle as multi
import nexus_regime_selected_exposure_increase as legacy_increase
import nexus_regime_selected_position_rebalance as legacy_rebalance


SOURCE_SHA = "a" * 40


def _regime_cell(symbol: str, timeframe: str) -> dict:
    core = {
        "schema_version": legacy_regime.CELL_SCHEMA,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_sha": SOURCE_SHA,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    return {**core, "cell_digest": legacy_regime._digest(core)}


def _regime_snapshot() -> dict:
    cells = [
        _regime_cell(symbol, timeframe)
        for symbol in multi.APPROVED_SYMBOLS
        for timeframe in multi.TIMEFRAMES
    ]
    core = {
        "schema_version": legacy_regime.SCHEMA,
        "matrix_id": "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2",
        "source_sha": SOURCE_SHA,
        "archive_sha256": None,
        "data_mode": "public_bybit_closed_candles",
        "context_digests": {symbol: str(index + 1) * 64 for index, symbol in enumerate(multi.APPROVED_SYMBOLS)},
        "expected_cell_count": 12,
        "verified_cell_count": 12,
        "cells": cells,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "frozen_prospective_hour4_lane_mutated": False,
    }
    return {**core, "cycle_digest": legacy_regime._digest(core)}


def _rebalance_cell(symbol: str, timeframe: str) -> dict:
    core = {
        "schema_version": legacy_rebalance.CELL_SCHEMA,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_sha": SOURCE_SHA,
        "action_count": 0,
        "actions": [],
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "exposure_increased": False,
    }
    return {**core, "cell_rebalance_digest": legacy_rebalance._digest(core)}


def _rebalance_snapshot(regime_digest: str) -> dict:
    cells = [
        _rebalance_cell(symbol, timeframe)
        for symbol in multi.APPROVED_SYMBOLS
        for timeframe in multi.TIMEFRAMES
    ]
    core = {
        "schema_version": legacy_rebalance.SCHEMA,
        "source_sha": SOURCE_SHA,
        "regime_cycle_digest": regime_digest,
        "cell_count": 12,
        "cells": cells,
        "held_count": 0,
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
    return {**core, "rebalance_digest": legacy_rebalance._digest(core)}


def _increase_cell(symbol: str, timeframe: str) -> dict:
    core = {
        "schema_version": legacy_increase.CELL_SCHEMA,
        "symbol": symbol,
        "timeframe": timeframe,
        "source_sha": SOURCE_SHA,
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
    return {**core, "cell_increase_digest": legacy_increase._digest(core)}


def _increase_snapshot(regime_digest: str, rebalance_digest: str) -> dict:
    cells = [
        _increase_cell(symbol, timeframe)
        for symbol in multi.APPROVED_SYMBOLS
        for timeframe in multi.TIMEFRAMES
    ]
    core = {
        "schema_version": legacy_increase.SCHEMA,
        "source_sha": SOURCE_SHA,
        "regime_cycle_digest": regime_digest,
        "rebalance_digest": rebalance_digest,
        "cell_count": 12,
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
    return {**core, "increase_digest": legacy_increase._digest(core)}


def _manifest() -> dict:
    return {
        "schema_version": "nexus.demo-strategy-matrix.v2",
        "matrix_id": "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2",
        "symbols": list(multi.APPROVED_SYMBOLS),
        "timeframes": list(multi.TIMEFRAMES),
        "families": list(multi.FAMILIES),
        "history_limit": 240,
        "authority": dict(multi.AUTHORITY),
        "migration": {},
    }


def test_v2_regime_accepts_exact_12_while_legacy_default_remains_six() -> None:
    value = _regime_snapshot()
    assert legacy_regime.verify_cycle_snapshot(value)["decision"] == "reject"
    assert multi.verify_v2_regime_snapshot(value)["decision"] == "pass"

    duplicate = deepcopy(value)
    duplicate["cells"][-1] = deepcopy(duplicate["cells"][0])
    unsigned = dict(duplicate)
    unsigned.pop("cycle_digest")
    duplicate["cycle_digest"] = legacy_regime._digest(unsigned)
    assert multi.verify_v2_regime_snapshot(duplicate)["decision"] == "reject"


def test_v2_rebalance_and_increase_keep_legacy_six_cell_verifiers_fail_closed() -> None:
    regime = _regime_snapshot()
    rebalance = _rebalance_snapshot(regime["cycle_digest"])
    increase = _increase_snapshot(regime["cycle_digest"], rebalance["rebalance_digest"])

    assert legacy_rebalance.verify_regime_selected_rebalance(rebalance)["decision"] == "reject"
    assert multi.verify_v2_rebalance(rebalance)["decision"] == "pass"
    assert legacy_increase.verify_regime_selected_exposure_increase(increase)["decision"] == "reject"
    assert multi.verify_v2_exposure_increase(increase)["decision"] == "pass"


def test_v2_rebalance_composes_two_verified_legacy_partitions(monkeypatch, tmp_path: Path) -> None:
    regime = _regime_snapshot()
    template = _rebalance_snapshot(regime["cycle_digest"])
    seen: list[tuple[str, ...]] = []

    def fake_run(*, manifest, regime_snapshot, **_kwargs):
        symbols = tuple(manifest["symbols"])
        seen.append(symbols)
        return multi._rebalance_group(
            template,
            symbols,
            regime_cycle_digest=regime_snapshot["cycle_digest"],
        )

    monkeypatch.setattr(multi.rebalance, "run_regime_selected_rebalance", fake_run)
    result = multi.run_v2_rebalance(
        manifest=_manifest(),
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        regime_snapshot=regime,
    )
    assert seen == list(multi.SYMBOL_GROUPS)
    assert result["cell_count"] == 12
    assert multi.verify_v2_rebalance(result)["decision"] == "pass"


def test_v2_increase_composes_two_verified_legacy_partitions(monkeypatch, tmp_path: Path) -> None:
    regime = _regime_snapshot()
    rebalance = _rebalance_snapshot(regime["cycle_digest"])
    template = _increase_snapshot(regime["cycle_digest"], rebalance["rebalance_digest"])
    seen: list[tuple[str, ...]] = []

    def fake_run(*, manifest, regime_snapshot, rebalance_snapshot, **_kwargs):
        symbols = tuple(manifest["symbols"])
        seen.append(symbols)
        return multi._increase_group(
            template,
            symbols,
            regime_cycle_digest=regime_snapshot["cycle_digest"],
            rebalance_digest=rebalance_snapshot["rebalance_digest"],
        )

    monkeypatch.setattr(multi.increase, "run_regime_selected_exposure_increase", fake_run)
    result = multi.run_v2_exposure_increase(
        manifest=_manifest(),
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        regime_snapshot=regime,
        rebalance_snapshot=rebalance,
    )
    assert seen == list(multi.SYMBOL_GROUPS)
    assert result["cell_count"] == 12
    assert multi.verify_v2_exposure_increase(result)["decision"] == "pass"
