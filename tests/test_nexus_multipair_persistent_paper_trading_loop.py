from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import nexus_multipair_persistent_paper_trading_loop as loop


SOURCE_SHA = "a" * 40


def _manifest() -> dict:
    return {
        "schema_version": "nexus.demo-strategy-matrix.v2",
        "matrix_id": "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2",
        "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"],
        "timeframes": ["minute15", "hour1", "hour4"],
        "families": ["momentum", "trend_breakout", "mean_reversion"],
        "history_limit": 240,
        "authority": {
            "paper_only": True,
            "live_trading_authority": False,
            "private_credentials_allowed": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        },
        "migration": {},
    }


def _matrix_state(*, fresh: int = 11) -> dict:
    cells = {}
    index = 0
    for symbol in _manifest()["symbols"]:
        for timeframe in _manifest()["timeframes"]:
            cells[f"{symbol}:{timeframe}"] = {
                "status": "VERIFIED",
                "source_sha": SOURCE_SHA if index < fresh else "b" * 40,
                "last_completed_open_ms": 1_728_000_000_000,
            }
            index += 1
    return {"cells": cells, "state_digest": "1" * 64}


def _migration() -> dict:
    core = {
        "schema_version": loop.MIGRATION_SCHEMA,
        "from_matrix_id": "nexus-demo-btc-eth-3tf-3strategy-v1",
        "from_manifest_sha256": "1" * 64,
        "from_state_digest": "2" * 64,
        "to_matrix_id": "nexus-demo-btc-eth-sol-xrp-3tf-3strategy-v2",
        "to_manifest_sha256": "3" * 64,
        "to_state_digest": "4" * 64,
        "preserved_cell_ids": [
            f"{symbol}:{timeframe}"
            for symbol in ("BTCUSDT", "ETHUSDT")
            for timeframe in ("minute15", "hour1", "hour4")
        ],
        "preserved_cell_count": 6,
        "new_symbols": ["SOLUSDT", "XRPUSDT"],
        "new_symbol_inherited_cell_count": 0,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
    }
    return {**core, "migration_digest": loop._matrix_digest(core)}


def _patch_common(monkeypatch, state: dict) -> None:
    monkeypatch.setattr(loop, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(loop, "_load_policy", lambda _path: {"policy": "verified"})
    monkeypatch.setattr(
        loop,
        "run_matrix_cycle",
        lambda **_kwargs: (deepcopy(state), {"snapshot_digest": "c" * 64}),
    )
    monkeypatch.setattr(loop, "verify_v2_snapshot", lambda *_args, **_kwargs: {"decision": "pass"})
    monkeypatch.setattr(
        loop,
        "build_discovery_status",
        lambda _root: {
            "controller_verified": True,
            "next_research_action": "nexus_multitimeframe_strategy_discovery",
            "summary": {"ready_search_stage_count": 7},
        },
    )
    monkeypatch.setattr(
        loop,
        "run_position_maintenance",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("maintenance must not run")),
    )
    monkeypatch.setattr(
        loop,
        "run_multipair_public_regime_cycle",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("regime must not run")),
    )


def test_restored_v1_state_migrates_once_then_reuses_v2_lineage(monkeypatch, tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    state_root.mkdir()
    (state_root / "matrix-state.json").write_text("{}", encoding="utf-8")
    state = _matrix_state(fresh=11)
    migration = _migration()
    calls = {"count": 0}

    def fake_load_or_migrate(*_args, **_kwargs):
        calls["count"] += 1
        return deepcopy(state), deepcopy(migration) if calls["count"] == 1 else None

    _patch_common(monkeypatch, state)
    monkeypatch.setattr(loop, "load_or_migrate_state", fake_load_or_migrate)

    first = loop.run_persistent_cycle(
        repo_root=tmp_path,
        state_root=state_root,
        source_sha=SOURCE_SHA,
        run_id="1001",
        now_ms=1_728_000_000_000,
        manifest_path=tmp_path / "v2.json",
        legacy_manifest_path=tmp_path / "v1.json",
        selector_policy_path=tmp_path / "policy.json",
    )
    assert first["expected_cell_count"] == 12
    assert first["expected_lane_count"] == 36
    assert first["fresh_cell_count"] == 11
    assert first["matrix_migration_status"] == "PERFORMED"
    assert first["legacy_preserved_cell_count"] == 6
    assert first["new_symbol_inherited_cell_count"] == 0
    assert loop.verify_loop_snapshot(first)["decision"] == "pass"
    evidence_path = state_root / "demo" / loop.MIGRATION_EVIDENCE_NAME
    assert evidence_path.is_file()

    second = loop.run_persistent_cycle(
        repo_root=tmp_path,
        state_root=state_root,
        source_sha=SOURCE_SHA,
        run_id="1002",
        now_ms=1_728_000_900_000,
        manifest_path=tmp_path / "v2.json",
        legacy_manifest_path=tmp_path / "v1.json",
        selector_policy_path=tmp_path / "policy.json",
    )
    assert calls["count"] == 2
    assert second["matrix_migration_status"] == "ALREADY_V2"
    assert second["matrix_migration_digest"] == first["matrix_migration_digest"]
    assert second["new_symbol_inherited_cell_count"] == 0
    assert loop.verify_loop_snapshot(second)["decision"] == "pass"


def test_v2_loop_verifier_rejects_legacy_shape_and_authority_widening(monkeypatch, tmp_path: Path) -> None:
    state = _matrix_state(fresh=11)
    _patch_common(monkeypatch, state)
    monkeypatch.setattr(loop, "load_or_migrate_state", lambda *_args, **_kwargs: (deepcopy(state), None))

    result = loop.run_persistent_cycle(
        repo_root=tmp_path,
        state_root=tmp_path / "fresh-state",
        source_sha=SOURCE_SHA,
        run_id="2001",
        now_ms=1_728_000_000_000,
        manifest_path=tmp_path / "v2.json",
        legacy_manifest_path=tmp_path / "v1.json",
        selector_policy_path=tmp_path / "policy.json",
    )
    assert result["matrix_migration_status"] == "FRESH_V2"
    assert loop.verify_loop_snapshot(result)["decision"] == "pass"

    legacy_shape = deepcopy(result)
    legacy_shape["expected_cell_count"] = 6
    legacy_shape["expected_lane_count"] = 18
    unsigned = dict(legacy_shape)
    unsigned.pop("loop_digest")
    legacy_shape["loop_digest"] = loop._digest(unsigned)
    assert loop.verify_loop_snapshot(legacy_shape)["decision"] == "reject"

    widened = deepcopy(result)
    widened["live_trading_authority"] = True
    unsigned = dict(widened)
    unsigned.pop("loop_digest")
    widened["loop_digest"] = loop._digest(unsigned)
    assert loop.verify_loop_snapshot(widened)["decision"] == "reject"
