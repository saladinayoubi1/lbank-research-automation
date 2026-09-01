from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import nexus_paper_acceptance_stage1 as audit


SOURCE_SHA = "a" * 40
STALE_SHA = "b" * 40
VERIFICATION_DIGEST = "f" * 64
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


def _write_ledgers(root: Path, *, substitute: bool = False) -> None:
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
            if substitute and symbol == "BTCUSDT" and timeframe == "hour1":
                tasks[0]["evidence_digest"] = "d" * 64
            ledger = {
                "source_sha": SOURCE_SHA,
                "symbol": symbol,
                "timeframe": timeframe,
                "paper_only": True,
                "live_trading_authority": False,
                "tasks": tasks,
                "final_status": "VERIFIED",
            }
            ledger["ledger_digest"] = audit._digest(ledger)
            _write_json(
                root / "cells" / symbol.lower() / timeframe / "supervisor-ledger.json",
                ledger,
            )


def _bind_matrix_evidence(matrix: dict, root: Path) -> None:
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            cell_root = root / "cells" / symbol.lower() / timeframe
            ledger = json.loads((cell_root / "supervisor-ledger.json").read_text(encoding="utf-8"))
            analysis_core = {
                "contract_version": "nexus.mission-control.paper-performance.v1",
                "supervisor_verification_digest": VERIFICATION_DIGEST,
                "paper_only": True,
                "live_trading_authority": False,
                "strategy_count": 0,
                "status_counts": {},
                "strategies": [],
            }
            analysis = {**analysis_core, "projection_digest": audit._digest(analysis_core)}
            _write_json(cell_root / "analysis" / "paper-performance.json", analysis)
            cell = matrix["cells"][f"{symbol}:{timeframe}"]
            cell["ledger_digest"] = ledger["ledger_digest"]
            cell["verification_digest"] = VERIFICATION_DIGEST
            cell["analysis_digest"] = analysis["projection_digest"]


def _mock_verification(_value: dict) -> dict:
    return {"decision": "pass", "verification_digest": VERIFICATION_DIGEST}


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


def test_stage1_rejects_detached_supervisor_ledger_binding(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    _write_ledgers(tmp_path)
    _bind_matrix_evidence(matrix, tmp_path)
    matrix["cells"]["BTCUSDT:hour1"]["ledger_digest"] = "0" * 64
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", _mock_verification)
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="ledger digest binding mismatch"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )


def test_stage1_rejects_detached_performance_binding(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    _write_ledgers(tmp_path)
    _bind_matrix_evidence(matrix, tmp_path)
    matrix["cells"]["BTCUSDT:hour1"]["analysis_digest"] = "0" * 64
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", _mock_verification)
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="per-cell performance binding mismatch"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )


def test_stage1_rejects_lane_ledger_substitution(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    _write_ledgers(tmp_path, substitute=True)
    _bind_matrix_evidence(matrix, tmp_path)
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", _mock_verification)
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="lane/ledger substitution"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )


def test_stage1_rejects_nonterminal_lane_outcome(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    matrix["cells"]["BTCUSDT:hour1"]["lanes"][0]["status"] = "WAITING"
    _write_ledgers(tmp_path)
    ledger_path = tmp_path / "cells" / "btcusdt" / "hour1" / "supervisor-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["tasks"][0]["status"] = "WAITING"
    ledger.pop("ledger_digest")
    ledger["ledger_digest"] = audit._digest(ledger)
    _write_json(ledger_path, ledger)
    _bind_matrix_evidence(matrix, tmp_path)
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", _mock_verification)
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", _loop())

    with pytest.raises(audit.PaperAcceptanceStage1Error, match="nonterminal or unapproved lane outcome"):
        audit.audit_state_root(
            state_root=tmp_path,
            manifest_path=tmp_path / "manifest.json",
            source_sha=SOURCE_SHA,
        )


def test_stage1_accepts_exact_operational_boundary_chain(monkeypatch, tmp_path: Path) -> None:
    matrix = _matrix()
    _write_ledgers(tmp_path)
    _bind_matrix_evidence(matrix, tmp_path)
    monkeypatch.setattr(audit, "load_manifest", lambda _path: _manifest())
    monkeypatch.setattr(audit, "load_state", lambda _path, _manifest: matrix)
    monkeypatch.setattr(audit, "verify_loop_snapshot", lambda _value: {"decision": "pass"})
    monkeypatch.setattr(audit, "verify_ledger", _mock_verification)
    monkeypatch.setattr(audit, "verify_cycle_snapshot", lambda _value: {"decision": "pass"})

    maintenance_core = {
        "source_sha": SOURCE_SHA,
        "cell_count": 6,
        "task_count": 18,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "exposure_increased": False,
    }
    maintenance = {**maintenance_core, "maintenance_digest": audit._digest(maintenance_core)}
    performance_core = {
        "source_sha": SOURCE_SHA,
        "cell_count": 6,
        "paper_only": True,
        "live_trading_authority": False,
        "automatic_strategy_promotion": False,
    }
    performance = {**performance_core, "refresh_digest": audit._digest(performance_core)}
    regime = {
        "source_sha": SOURCE_SHA,
        "expected_cell_count": 6,
        "verified_cell_count": 6,
        "paper_only": True,
        "live_trading_authority": False,
        "private_credentials_used": False,
        "automatic_strategy_promotion": False,
        "deterministic_risk_final_authority": True,
        "cycle_digest": "e" * 64,
    }
    loop = {
        **_loop(),
        "regime_status": "VERIFIED",
        "performance_health_feedback_operational": True,
        "regime_selected_rebalance_operational": True,
        "regime_selected_exposure_increase_operational": True,
        "strategy_research_required": True,
        "strategy_discovery_health_trigger_requested": True,
        "remaining_core_gap": "RUNTIME_EVIDENCE_AND_DISCOVERY_FEEDBACK_PROOF",
        "maintenance_digest": maintenance["maintenance_digest"],
        "performance_refresh_digest": performance["refresh_digest"],
        "regime_cycle_digest": regime["cycle_digest"],
    }
    _write_json(tmp_path / "demo" / "persistent-paper-trading-loop.json", loop)
    _write_json(tmp_path / "demo" / "paper-position-maintenance.json", maintenance)
    _write_json(tmp_path / "demo" / "paper-performance-refresh.json", performance)
    _write_json(tmp_path / "demo" / "regime-cycle.json", regime)

    result = audit.audit_state_root(
        state_root=tmp_path,
        manifest_path=tmp_path / "manifest.json",
        source_sha=SOURCE_SHA,
    )

    assert result["decision"] == "pass"
    assert result["verified_cell_count"] == 6
    assert result["verified_lane_count"] == 18
    assert result["health_trigger_requested"] is True
    assert result["stage1_only"] is True
    assert result["discovery_runtime_requalification_proven"] is False
    assert result["restart_replay_proven"] is False
