from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import nexus_paper_acceptance_stage1 as audit


SOURCE_SHA = "a" * 40
STALE_SHA = "b" * 40
FAMILIES = ["momentum", "trend_breakout", "mean_reversion"]
SYMBOLS = ["BTCUSDT", "ETHUSDT"]
TIMEFRAMES = ["minute15", "hour1", "hour4"]


def _manifest() -> dict:
    return {"symbols": SYMBOLS, "timeframes": TIMEFRAMES, "families": FAMILIES}


def _matrix(source_sha: str = SOURCE_SHA) -> dict:
    cells = {}
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            cell_id = f"{symbol}:{timeframe}"
            cells[cell_id] = {
                "cell_id": cell_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "status": "VERIFIED",
                "source_sha": source_sha,
                "lanes": [
                    {
                        "family": family,
                        "task_id": f"task-{family}",
                        "status": "qualification_killed",
                        "evidence_digest": "c" * 64,
                    }
                    for family in FAMILIES
                ],
            }
    return {"cells": cells}


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _loop() -> dict:
    return {
        "source_sha": SOURCE_SHA,
        "status": "PAPER_LOOP_ACTIVE",
        "fresh_cell_count": 6,
        "fresh_cells": [f"{s}:{t}" for s in SYMBOLS for t in TIMEFRAMES],
        "expected_cell_count": 6,
        "expected_lane_count": 18,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
    }


def test_stage1_rejects_one_stale_source_cell(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    matrix["cells"]["BTCUSDT:hour1"]["source_sha"] = STALE_SHA
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="exact-source VERIFIED"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )


def test_stage1_rejects_lane_ledger_substitution(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", lambda _value: {"decision": "pass"})
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            tasks = [
                {
                    "family": family,
                    "task_id": f"task-{family}",
                    "status": "qualification_killed",
                    "evidence_digest": "c" * 64,
                }
                for family in FAMILIES
            ]
            if symbol == "BTCUSDT" and timeframe == "hour1":
                tasks[0]["evidence_digest"] = "d" * 64
            _write_json(
                tmp_path / "cells" / symbol.lower() / timeframe / "supervisor-ledger.json",
                {
                    "source_sha": SOURCE_SHA,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "paper_only": True,
                    "live_trading_authority": False,
                    "tasks": tasks,
                },
            )

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="lane/ledger substitution"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )
