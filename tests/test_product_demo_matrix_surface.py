from __future__ import annotations

import json
from pathlib import Path

from nexus_demo_strategy_matrix import run_matrix_cycle
from product_web_server import _demo_matrix_snapshot


def _runner(**kwargs):
    tasks = [{
        "family": family,
        "task_id": f"{kwargs['symbol']}:{kwargs['timeframe']}:{family}",
        "status": "qualification_killed",
        "evidence_digest": family[0] * 64,
    } for family in kwargs["families"]]
    return {
        "symbol": kwargs["symbol"], "timeframe": kwargs["timeframe"],
        "paper_only": True, "live_trading_authority": False,
        "tasks": tasks, "ledger_digest": "a" * 64,
    }


def _verifier(_ledger):
    return {"decision": "pass", "verification_digest": "b" * 64}


def _analyzer(_root, _ledger):
    return {
        "paper_only": True, "live_trading_authority": False,
        "status_counts": {}, "projection_digest": "c" * 64,
    }


def _manifest():
    return {
        "schema_version": "nexus.demo-strategy-matrix.v1",
        "matrix_id": "nexus-demo-btc-eth-3tf-3strategy-v1",
        "symbols": ["BTCUSDT", "ETHUSDT"],
        "timeframes": ["minute15", "hour1", "hour4"],
        "families": ["momentum", "trend_breakout", "mean_reversion"],
        "history_limit": 240,
        "authority": {
            "paper_only": True, "live_trading_authority": False,
            "private_credentials_allowed": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        },
    }


def test_product_demo_reads_verified_matrix_snapshot(tmp_path: Path) -> None:
    state = {
        "schema_version": "nexus.demo-strategy-matrix-state.v1",
        "matrix_id": _manifest()["matrix_id"],
        "manifest_sha256": "unused-by-cycle",
        "cells": {}, "paper_only": True, "live_trading_authority": False,
        "private_credentials_used": False, "automatic_strategy_promotion": False,
        "state_digest": "unused-by-cycle",
    }
    _, snapshot = run_matrix_cycle(
        manifest=_manifest(), state=state, state_root=tmp_path,
        source_sha="a" * 40, run_id="1", now_ms=1_800_000_000_000,
        runner=_runner, verifier=_verifier, analyzer=_analyzer,
    )
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "strategy-matrix.json").write_text(json.dumps(snapshot), encoding="utf-8")

    payload = _demo_matrix_snapshot(tmp_path / "market")
    assert payload["status"] == "VERIFIED"
    assert payload["expected_lane_count"] == 18
    assert payload["paper_only"] is True
    assert payload["live_trading_authority"] is False


def test_product_demo_fails_closed_on_missing_or_tampered_snapshot(tmp_path: Path) -> None:
    missing = _demo_matrix_snapshot(tmp_path / "market")
    assert missing["status"] == "unavailable"
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "strategy-matrix.json").write_text('{"snapshot_digest":"bad"}', encoding="utf-8")
    tampered = _demo_matrix_snapshot(tmp_path / "market")
    assert tampered["status"] == "unavailable"
    assert tampered["reason"] == "snapshot_verification_failed"
