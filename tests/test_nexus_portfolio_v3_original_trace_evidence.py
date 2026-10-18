"""Independently reconcile audited native v3 fill journal evidence and old v3 P/L."""
from __future__ import annotations
from hashlib import sha256
import json
from pathlib import Path

import pytest

from research.portfolio_v3_original_fill_journal import _digest
from scripts import nexus_existing_portfolio_shared500_diagnostic as old

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/q1-and-3y-fifo-audited-500.json"
DIGEST="6b8eef57f59cd5af44c09b74e58ff92d93b395026996db196bf1a422ba6d56fd"
PREVIOUS_Q1="67c3817359fb4b9a225cc89c6abcd5a405b5602c4e3f20d822056fa1515ad746"
PREVIOUS_FULL="63afc60f7e35fbe456a4a43b3dc061e6b253d33d46e60b0fa95725ca29050077"


def load():
    data=json.loads(EVIDENCE.read_text("utf8"))
    expect=_digest({k:v for k,v in data.items() if k!="digest"})
    assert data["digest"]==DIGEST==expect
    return data


def test_historical_research_boundary_and_source_sha6():
    d=load()
    assert d["schema"]=="nexus.portfolio-v3-500-attested-fifo-research-evidence.v1"
    assert d["source_historical_preinspected_not_untouched_future"] is True
    assert d["original_exact_execution_policy_unchanged"] is True
    assert d["physical_stop_loss_existed_in_original_engine"] is False
    assert d["risk_gap_still_unbounded"] is True
    assert d["trading_strategy_newly_generated"] is False
    assert d["paper_eligible"] is False
    assert d["live_enabled"] is False
    assert d["orders"]==0
    assert set(d["scopes"])=={"2025Q1","2023_2026_CONTINUOUS"}
    for scope in d["scopes"].values():
        assert len(scope["source_six_raw_sha256"])==6
        assert set(scope["cost_profiles"])=={"conservative","stress","severe"}


def test_exact_q1_pnl_and_cash_reconcile_with_prior_original_engine():
    d=load()["scopes"]["2025Q1"]
    old_evidence=json.loads((ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/"
                             "fixed-dual-rotation-2025q1-original.json").read_text("utf8"))
    assert old_evidence["result_sha256"]==PREVIOUS_Q1
    for profile in ("conservative","stress","severe"):
        new=d["cost_profiles"][profile]
        prior=old_evidence["segments"]["2025_Q1_CONTINUOUS"][profile]
        assert new["net_pnl_usdt"]==pytest.approx(prior["net_pnl_usdt"],abs=1e-6)
        assert new["total_fees_usdt"]==pytest.approx(prior["fees_usdt"],abs=1e-6)
        assert new["observed_max_drawdown_pct"]==pytest.approx(prior["max_drawdown_pct"],abs=1e-6)
        assert new["actual_original_execution_fills"]==prior["asset_fill_events"]==9
        assert new["closed_fifo_lot_segments"]==8
        assert new["winning_fifo_lot_segments"]==7


def test_exact_multiyear_pnl_drawdown_costs_reconcile_original_model():
    d=load()["scopes"]["2023_2026_CONTINUOUS"]
    prior=json.loads((ROOT/"docs/evidence/portfolio-v3-original-500-calibration-20261018/"
        "fixed-dual-rotation-2023-2026-six-regimes-vs-passive.json").read_text("utf8"))
    assert prior["digest"]==PREVIOUS_FULL
    for profile in ("conservative","stress","severe"):
        original=prior["periods"]["2023_09_to_2026_08_CONTINUOUS"]["strategies"][
            "original_v3_dual_rotation_fixed"][profile]
        j=d["cost_profiles"][profile]
        assert j["net_pnl_usdt"]==pytest.approx(original["net_usdt"],abs=1e-6)
        assert j["observed_max_drawdown_pct"]==pytest.approx(original["max_drawdown_pct"],abs=1e-6)
        assert j["total_fees_usdt"]==pytest.approx(original["paid_fees_usdt"],abs=1e-6)
        assert j["actual_original_execution_fills"]==original["asset_fill_count"]==106
        assert j["closed_fifo_lot_segments"]==88
        assert j["btc_fills"]+j["eth_fills"]==106
        assert j["terminal_cash_usdt"]==pytest.approx(500+j["net_pnl_usdt"],abs=1e-6)


def test_monthly_fifo_segments_reconcile_not_fabricated_trade_counts():
    d=load()
    for scope in d["scopes"].values():
        for row in scope["cost_profiles"].values():
            months=row["monthly_by_fifo_exit_month"]
            assert sum(x["fifo_matched_lot_segments"] for x in months.values())==row["closed_fifo_lot_segments"]
            assert sum(x["winning_segments"] for x in months.values())==row["winning_fifo_lot_segments"]
            assert sum(x["net_pnl_usdt"] for x in months.values())==pytest.approx(row["net_pnl_usdt"],abs=2e-6)
            assert row["mean_net_pnl_per_fifo_matched_segment_usdt"]==pytest.approx(
                row["net_pnl_usdt"]/row["closed_fifo_lot_segments"],abs=1e-6)


def test_audited_source_full_traces_are_local_not_misrepresented_as_uploaded():
    d=load()
    for scope in d["scopes"].values():
        assert scope["full_ledger_local_path"].endswith("-original-fill-journal.json")
        assert len(scope["full_ledger_local_sha256"])==64
        assert len(scope["full_original_report_digest"])==64
        assert len(scope["original_engine_module_sha256"])==64
        assert scope["fixed_old_candidate_id"]=="b4e4a2c33304aec1"
