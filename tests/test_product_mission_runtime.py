from __future__ import annotations

import json
from pathlib import Path

import pytest

from product_mission_runtime import ProductMissionError, ProductMissionRuntime, SNAPSHOT_CONTRACT, StrategyEvidenceStore


def _config() -> dict:
    return {
        "schema_version": 1,
        "phase": 6,
        "policy": {"l4_owner_required": True, "independent_verification_required": True},
        "workers": [
            {"id": "developer-agent", "capabilities": ["implementation"], "resources": ["github-cloud"], "authority_max": 3, "enabled": True, "verifier": False, "max_concurrent_tasks": 1},
            {"id": "windows-runner", "capabilities": ["windows_runtime"], "resources": ["windows-local"], "authority_max": 3, "enabled": True, "verifier": True, "max_concurrent_tasks": 1},
        ],
        "tasks": [
            {"id": "T1", "title": "Build product", "phase": 6, "gate": 1, "status": "PENDING", "priority": 90, "dependencies": [], "required_capabilities": ["implementation"], "preferred_resources": ["github-cloud"], "authority": 2, "acceptance": ["verified"]},
            {"id": "L4", "title": "Enable live", "phase": 6, "gate": 99, "status": "PENDING", "priority": 1, "dependencies": [], "required_capabilities": [], "preferred_resources": [], "authority": 4, "acceptance": ["owner only"]},
        ],
    }


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_definition_only_is_truthful_unknown_not_fabricated_runtime(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    _write(config_path, _config())
    mission = ProductMissionRuntime(tmp_path / "state", config_path=config_path)
    snapshot = mission.snapshot()
    assert snapshot["source"] == "definition_only"
    assert snapshot["control_plane"]["runtime_present"] is False
    assert {worker["state"] for worker in snapshot["workers"]} == {"UNKNOWN"}
    assert snapshot["owner_action_required"] is False
    assert snapshot["owner_actions"] == []
    assert snapshot["ci_health"]["status"] == "unavailable"
    assert snapshot["live_trading_authority"] is False


def test_real_runtime_surfaces_assignment_recovery_and_only_true_owner_action(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config = _config(); _write(config_path, config)
    runtime = json.loads(json.dumps(config))
    runtime["tasks"][0].update({"status": "RUNNING", "assigned_worker": "developer-agent", "heartbeat_at": "2026-08-18T10:00:00Z", "attempt": 2, "dispatch_transport": "github-cloud"})
    runtime["tasks"][1].update({"status": "OWNER_REQUIRED", "blocked_reason": "L4 owner approval required"})
    root = tmp_path / "state"
    _write(root / "agent_coordination" / "agent_manager_runtime.json", runtime)
    _write(root / "agent_coordination" / "manager_state.json", {"generated_at": "2026-08-18T10:00:00Z"})
    (root / "agent_coordination" / "manager_events.jsonl").write_text(json.dumps({"at":"2026-08-18T10:00:00Z","kind":"task_leased","task_id":"T1"}) + "\n", encoding="utf-8")
    snapshot = ProductMissionRuntime(root, config_path=config_path).snapshot()
    assert snapshot["source"] == "local_runtime"
    assert snapshot["control_plane"]["runtime_present"] is True
    assert snapshot["control_plane"]["active_tasks"][0]["id"] == "T1"
    dev = next(worker for worker in snapshot["workers"] if worker["id"] == "developer-agent")
    assert dev["state"] == "BUSY"
    assert snapshot["owner_action_required"] is True
    assert [row["id"] for row in snapshot["owner_actions"]] == ["L4"]
    assert snapshot["events"][0]["kind"] == "task_leased"


def test_snapshot_import_preserves_real_control_plane_ci_evidence_without_internet(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"; config = _config(); _write(config_path, config)
    mission = ProductMissionRuntime(tmp_path / "state", config_path=config_path)
    ci_event = {
        "at": "2026-08-18T10:00:00Z",
        "kind": "ci_snapshot",
        "payload": {
            "repo": "saladinayoubi1/lbank-research-automation",
            "summary": {"RUNNING":0,"WAITING":0,"DONE":5,"FAILED":0,"BLOCKED":0,"UNKNOWN":0},
            "local_node": {"internet_reachable": True},
            "workflows": {
                "Test": {"state":"DONE","run_id":100,"run_attempt":1,"conclusion":"success","status":"completed","head_sha":"a"*40,"updated_at":"2026-08-18T10:00:00Z","url":"https://example.invalid","auto_retry":{"attempted":False}},
                "Build": {"state":"DONE","run_id":101,"run_attempt":1,"conclusion":"success","status":"completed","head_sha":"a"*40,"updated_at":"2026-08-18T10:00:00Z","url":"https://example.invalid","auto_retry":{"attempted":False}},
            },
        },
    }
    imported = {
        "contract_version": SNAPSHOT_CONTRACT,
        "generated_at": "2026-08-18T10:00:00Z",
        "source": "github-cloud",
        "config": config,
        "runtime": {**config, "tasks": [{**config["tasks"][0], "status":"DONE", "verified_at":"2026-08-18T09:59:00Z"}, config["tasks"][1]]},
        "summary": {"generated_at":"2026-08-18T10:00:00Z"},
        "events": [{"at":"2026-08-18T09:59:00Z","kind":"task_done","task_id":"T1"}, ci_event],
        "paper_only": True,
        "live_trading_authority": False,
    }
    mission.import_snapshot(imported)
    snapshot = mission.snapshot()
    assert snapshot["source"] == "imported_snapshot"
    assert snapshot["tasks"][0]["status"] == "DONE"
    assert snapshot["control_plane"]["verified_progress_percent"] == 100.0
    assert snapshot["ci_health"]["status"] == "available"
    assert snapshot["ci_health"]["state"] == "DONE"
    assert snapshot["ci_health"]["single_exact_head"] is True
    assert snapshot["ci_health"]["head_shas"] == ["a" * 40]


def test_snapshot_import_rejects_authority_widening_and_invalid_timestamp(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"; config = _config(); _write(config_path, config)
    mission = ProductMissionRuntime(tmp_path / "state", config_path=config_path)
    payload = {"contract_version":SNAPSHOT_CONTRACT,"generated_at":"2026-08-18T10:00:00Z","source":"x","config":config,"runtime":None,"summary":None,"events":[],"paper_only":True,"live_trading_authority":True}
    with pytest.raises(ProductMissionError, match="widened authority"):
        mission.import_snapshot(payload)
    payload["live_trading_authority"] = False
    payload["generated_at"] = "not-a-time"
    with pytest.raises(ProductMissionError, match="generated_at invalid"):
        mission.import_snapshot(payload)


def _run(family: str, status: str, oos: float, walk: float, robust: float, dd: float) -> dict:
    return {
        "paper_only": True,
        "profitability_claim": False,
        "request": {"family": family, "symbol":"BTCUSDT", "timeframe":"minute15"},
        "dataset": {"instrument":"BTC/USDT", "source":"Bybit", "binding_sha256": family * 8},
        "qualification": {"status":status, "kill_reasons":[] if status == "paper_candidate" else ["OOS_KILL"]},
        "evidence": {"oos_score":oos,"walk_forward_score":walk,"robustness_score":robust,"max_drawdown_pct":dd,"cost_stress_loss_pct":1.0,"regime_pass_ratio":0.67,"failure_mode_severity":0.5,"benchmark_score":0.01},
        "cost_model": {"fee_bps":10,"slippage_bps":5},
    }


def test_strategy_center_uses_qualification_evidence_not_single_backtest(tmp_path: Path) -> None:
    store = StrategyEvidenceStore(tmp_path)
    store.record(_run("momentum", "paper_candidate", 0.01, 0.02, 0.01, 12.0))
    store.record(_run("trend_breakout", "paper_candidate", 0.03, 0.01, 0.02, 20.0))
    store.record(_run("mean_reversion", "killed", 0.50, 0.50, 0.50, 1.0))
    center = store.history()
    assert center["candidate_count"] == 2
    assert center["leading_candidate"]["request"]["family"] == "trend_breakout"
    assert center["profitability_claim"] is False
    assert "OOS" in center["ranking_rule"]


def test_strategy_zero_score_is_real_evidence_not_missing(tmp_path: Path) -> None:
    store = StrategyEvidenceStore(tmp_path)
    store.record(_run("momentum", "paper_candidate", -0.01, 0.10, 0.10, 2.0))
    store.record(_run("trend_breakout", "paper_candidate", 0.0, -0.50, -0.50, 30.0))
    center = store.history()
    assert center["leading_candidate"]["request"]["family"] == "trend_breakout"
