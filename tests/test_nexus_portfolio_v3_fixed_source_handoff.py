"""Preparation must preserve the old strategy and remain undispatched."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import agent_manager as am

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "research/portfolio_v3_fixed_source_handoff_20261019.json"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_fixed_handoff_binds_original_engine_candidate_and_frozen_window():
    spec = read(SPEC)
    cal = read(ROOT / "research/portfolio_existing_engine_shared500_calibration_v1.json")
    freeze = read(ROOT / "research/portfolio_v3_forward_bybit_source_freeze_20261018.json")
    identity = hashlib.sha256(json.dumps(cal["candidate"], sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()[:16]
    assert identity == spec["candidate_id"] == "b4e4a2c33304aec1"
    assert spec["candidate"] == cal["candidate"]
    assert spec["cost_profiles"] == freeze["original_execution_cost_profiles"]
    assert spec["risk_comparisons"]["fixed_posthoc_dd20"] == freeze["risk_policy"]
    assert spec["comparators"] == freeze["comparators"]
    assert spec["future_study"]["start_utc"] == freeze["future_scoring_start_utc"]
    assert spec["future_study"]["end_exclusive_utc"] == freeze["future_scoring_end_exclusive_utc"]
    for relative, sha in spec["code_and_contract_sha256_lf_normalized"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == sha


def test_preparation_cannot_claim_new_backtest_or_paper_authority():
    spec = read(SPEC)
    assert spec["future_study"]["source_prices_read_in_this_preparation"] is False
    assert spec["source_requirements"]["warmup_is_not_independent_strategy_score"] is True
    assert spec["source_requirements"]["original_V5_only_future_preflight_unchanged"] is True
    assert spec["source_requirements"]["future_archive_source_policy_separately_required"] is True
    assert spec["initial_shared_cash_usdt"] == 500
    assert spec["rebalance"]["bars"] == 42
    assert spec["rebalance"]["original_grid_anchor_utc"] == "2022-12-01T00:00:00Z"
    assert spec["minimum_trade_count"] is None
    assert all(spec[k] is False for k in ("strategy_backtest_performed", "economic_edge_established",
                                         "automatic_strategy_promotion", "paper_eligible", "live_enabled"))


def test_real_manager_definition_records_blocked_preparation_without_dispatch():
    config = read(ROOT / "config/nexus-agent-manager.json")
    sha = hashlib.sha256(SPEC.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    task_id = "P7-PORTFOLIO-FORWARD-PREP-" + sha[:16]
    rows = [t for t in config["tasks"] if t["id"] == task_id]
    assert len(rows) == 1
    task = rows[0]
    assert task["status"] == "BLOCKED" and task["authority"] == 2
    assert "2027-01-17" in task["blocked_reason"]
    assert sha in " ".join(task["acceptance"])
    assert task["required_resources"] == ["windows-local"]
    assert "source_system_development_task" not in task
    am.validate_config(config)
    isolated = {**deepcopy(config), "tasks": [deepcopy(task)]}
    am.release_ready_tasks(isolated)
    assert isolated["tasks"][0]["status"] == "BLOCKED"
    assert "assigned_worker" not in isolated["tasks"][0]
