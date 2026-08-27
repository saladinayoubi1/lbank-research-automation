from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import nexus_persistent_paper_trading_loop as loop
import nexus_public_regime_cycle as public_regime
from nexus_demo_regime_cycle import CELL_SCHEMA, SCHEMA as REGIME_SCHEMA, _digest as regime_digest


SOURCE_SHA = "a" * 40


def _manifest() -> dict:
    return {
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "timeframes": ["minute15", "hour1", "hour4"],
        "families": ["momentum", "trend_breakout", "mean_reversion"],
    }


def _matrix_state(*, fresh: int = 6) -> dict:
    rows = {}
    index = 0
    for symbol in _manifest()["symbols"]:
        for timeframe in _manifest()["timeframes"]:
            rows[f"{symbol}:{timeframe}"] = {
                "status": "VERIFIED",
                "source_sha": SOURCE_SHA if index < fresh else "b" * 40,
                "last_completed_open_ms": 1_728_000_000_000 - {
                    "minute15": 900_000,
                    "hour1": 3_600_000,
                    "hour4": 14_400_000,
                }[timeframe],
            }
            index += 1
    return {"cells": rows}


def _matrix_snapshot() -> dict:
    return {"snapshot_digest": "c" * 64}


def _regime_snapshot() -> dict:
    cells = []
    for symbol in _manifest()["symbols"]:
        for timeframe in _manifest()["timeframes"]:
            core = {
                "schema_version": CELL_SCHEMA,
                "symbol": symbol,
                "timeframe": timeframe,
                "source_sha": SOURCE_SHA,
                "paper_only": True,
                "live_trading_authority": False,
                "private_credentials_used": False,
                "automatic_strategy_promotion": False,
                "deterministic_risk_final_authority": True,
                "cash_weight": "1.000000",
            }
            cells.append({**core, "cell_digest": regime_digest(core)})
    core = {
        "schema_version": REGIME_SCHEMA,
        "matrix_id": "matrix",
        "source_sha": SOURCE_SHA,
        "archive_sha256": None,
        "data_mode": public_regime.PUBLIC_DATA_MODE,
        "context_digests": {"BTCUSDT": "d" * 64, "ETHUSDT": "e" * 64},
        "expected_cell_count": 6,
        "verified_cell_count": 6,
        "cells": cells,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "frozen_prospective_hour4_lane_mutated": False,
    }
    return {**core, "cycle_digest": regime_digest(core)}


def _patch_common(monkeypatch, matrix_state: dict) -> None:
    monkeypatch.setattr(loop, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(loop, "_load_policy", lambda _path: {"policy": "verified"})
    monkeypatch.setattr(loop, "load_state", lambda _path, _manifest: {})
    monkeypatch.setattr(
        loop,
        "run_matrix_cycle",
        lambda **_kwargs: (matrix_state, _matrix_snapshot()),
    )
    monkeypatch.setattr(loop, "verify_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(
        loop,
        "build_discovery_status",
        lambda _root: {
            "controller_verified": True,
            "next_research_action": "nexus_multitimeframe_strategy_discovery",
            "summary": {"ready_search_stage_count": 7},
        },
    )


def test_stale_source_cell_waits_and_cannot_trade(monkeypatch, tmp_path: Path) -> None:
    _patch_common(monkeypatch, _matrix_state(fresh=5))
    monkeypatch.setattr(
        loop,
        "run_position_maintenance",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("maintenance must not run")),
    )
    monkeypatch.setattr(
        loop,
        "run_public_regime_cycle",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("regime must not run")),
    )

    result = loop.run_persistent_cycle(
        repo_root=tmp_path,
        state_root=tmp_path / "state",
        source_sha=SOURCE_SHA,
        run_id="123",
        now_ms=1_728_000_000_000,
        manifest_path=tmp_path / "manifest.json",
        selector_policy_path=tmp_path / "policy.json",
    )

    assert result["status"] == "WAITING_FOR_FRESH_CELLS"
    assert result["fresh_cell_count"] == 5
    assert result["regime_cycle_digest"] is None
    assert result["trading_engine_complete"] is False
    assert loop.verify_loop_snapshot(result)["decision"] == "pass"


def test_fresh_public_cycle_runs_risk_reducing_maintenance_regime_and_discovery(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_common(monkeypatch, _matrix_state(fresh=6))
    monkeypatch.setattr(
        loop,
        "run_position_maintenance",
        lambda **_kwargs: {"maintenance_digest": "1" * 64, "exposure_increased": False},
    )
    monkeypatch.setattr(
        loop,
        "run_performance_refresh",
        lambda **_kwargs: {
            "refresh_digest": "2" * 64,
            "rows": [{"status_counts": {"HEALTHY": 1}}],
        },
    )
    monkeypatch.setattr(
        loop,
        "_regime_boundary",
        lambda _state, _symbols: {"BTCUSDT": 1_728_000_000_000, "ETHUSDT": 1_728_000_000_000},
    )
    regime = _regime_snapshot()
    monkeypatch.setattr(loop, "run_public_regime_cycle", lambda **_kwargs: deepcopy(regime))
    monkeypatch.setattr(loop, "verify_cycle_snapshot", lambda _value: {"decision": "pass"})

    result = loop.run_persistent_cycle(
        repo_root=tmp_path,
        state_root=tmp_path / "state",
        source_sha=SOURCE_SHA,
        run_id="124",
        now_ms=1_728_000_000_000,
        manifest_path=tmp_path / "manifest.json",
        selector_policy_path=tmp_path / "policy.json",
    )

    assert result["status"] == "PAPER_LOOP_ACTIVE"
    assert result["fresh_cell_count"] == 6
    assert result["regime_status"] == "VERIFIED"
    assert result["strategy_research_required"] is True  # 100% cash requests more research.
    assert result["strategy_discovery_controller_verified"] is True
    assert result["regime_selected_rebalance_operational"] is False
    assert result["remaining_core_gap"] == "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE"
    assert loop.verify_loop_snapshot(result)["decision"] == "pass"


def test_loop_verifier_rejects_authority_or_completion_fabrication() -> None:
    core = {
        "schema_version": loop.SCHEMA,
        "source_sha": SOURCE_SHA,
        "run_id": "1",
        "now_ms": 1,
        "status": "WAITING_FOR_FRESH_CELLS",
        "data_mode": public_regime.PUBLIC_DATA_MODE,
        "matrix_snapshot_digest": "a" * 64,
        "expected_cell_count": 6,
        "fresh_cell_count": 5,
        "fresh_cells": ["a", "b", "c", "d", "e"],
        "expected_lane_count": 18,
        "regime_status": "WAITING_FOR_FRESH_CELLS",
        "regime_cycle_digest": None,
        "maintenance_digest": None,
        "performance_refresh_digest": None,
        "strategy_discovery_controller_verified": True,
        "strategy_discovery_next_action": "research",
        "strategy_discovery_ready_stage_count": 7,
        "strategy_research_required": False,
        "strategy_discovery_rotation": "automatic_daily_bounded_rotation",
        "persistent_state_digest": "b" * 64,
        "comparison_position_lifecycle": "OPEN_HOLD_RISK_REDUCING_CLOSE",
        "regime_selected_rebalance_operational": False,
        "remaining_core_gap": "REGIME_SELECTED_POSITION_CLOSE_AND_RESIZE",
        "trading_engine_complete": False,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }
    snapshot = {**core, "loop_digest": loop._digest(core)}
    assert loop.verify_loop_snapshot(snapshot)["decision"] == "pass"

    tampered = deepcopy(snapshot)
    tampered["live_trading_authority"] = True
    assert loop.verify_loop_snapshot(tampered)["decision"] == "reject"

    fabricated = deepcopy(snapshot)
    fabricated["trading_engine_complete"] = True
    unsigned = dict(fabricated)
    unsigned.pop("loop_digest")
    fabricated["loop_digest"] = loop._digest(unsigned)
    assert loop.verify_loop_snapshot(fabricated)["decision"] == "reject"


def test_public_regime_adapter_rebinds_archive_provenance_and_rebalance(
    monkeypatch, tmp_path: Path
) -> None:
    historical = _regime_snapshot()
    historical.pop("data_mode")
    historical["archive_sha256"] = "f" * 64
    unsigned = dict(historical)
    unsigned.pop("cycle_digest")
    historical["cycle_digest"] = regime_digest(unsigned)
    rebalance = {
        "rebalance_digest": "9" * 64,
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

    monkeypatch.setattr(public_regime, "run_demo_regime_cycle", lambda **_kwargs: deepcopy(historical))
    monkeypatch.setattr(
        public_regime, "run_regime_selected_rebalance", lambda **_kwargs: deepcopy(rebalance)
    )
    monkeypatch.setattr(
        public_regime,
        "verify_regime_selected_rebalance",
        lambda _value: {"decision": "pass"},
    )
    result = public_regime.run_public_regime_cycle(
        manifest=_manifest(),
        matrix_state=_matrix_state(),
        state_root=tmp_path,
        source_sha=SOURCE_SHA,
        selector_policy={},
    )

    assert result["archive_sha256"] is None
    assert result["data_mode"] == public_regime.PUBLIC_DATA_MODE
    assert result["regime_selected_rebalance_digest"] == "9" * 64
    assert result["risk_reducing_rebalance_operational"] is True
    assert result["regime_selected_exposure_increase_operational"] is False
    assert result["regime_selected_rebalance_operational"] is False
    assert result["regime_selected_rebalance_remaining_gap"] == (
        "REGIME_SELECTED_EXPOSURE_INCREASE_WITH_FRESH_RISK"
    )
    assert result["cycle_digest"] == regime_digest({k: v for k, v in result.items() if k != "cycle_digest"})
    assert public_regime.verify_cycle_snapshot(result)["decision"] == "pass"
