"""Fixed two-source, three-cost risk switch historical research receipt QA."""
from __future__ import annotations
import json
import pytest
from pathlib import Path

from scripts import nexus_portfolio_v3_causal_dd20_diagnostic as pilot
from scripts.nexus_existing_portfolio_shared500_diagnostic import _load_contract,ROOT
from scripts.nexus_strategy_finder_shared_cash_eval import PINNED_BYBIT_PARQUET_SHA256

EVIDENCE=Path(__file__).resolve().parents[1]/"docs/evidence/portfolio-v3-original-500-calibration-20261018/fixed-causal-dd20-vs-unchanged-2025q1-2023to2026.json"
EXPECTED="22f723c4ef707cbb51f903593ba0510d3c5a21e2ca2659c4ae6f1b376481ad46"


def data():
    o=json.loads(EVIDENCE.read_text("utf8"))
    assert o["digest"]==EXPECTED==pilot._digest({k:v for k,v in o.items() if k!="digest"})
    return o


def test_real_source_receipt_is_exact_source_locked_and_research_only():
    o=data()
    assert o["source_six_raw_sha256"]==PINNED_BYBIT_PARQUET_SHA256
    assert len(o["engine_module_sha256"])==64
    assert o["original_reviewed_fixed_candidate_id"]=="b4e4a2c33304aec1"
    _,sha=_load_contract(ROOT/pilot.DEFAULT_CONFIG)
    assert o["original_fixed_config_digest"]==sha
    assert o["source_already_inspected_not_future_holdout"] is True
    assert o["prior_historical_original_drawdown_already_known"] is True
    assert o["threshold_selection_not_prospective_blind"] is True
    assert o["one_shared_spot_cash_initial_usdt"]==500.
    assert o["paper_eligible"] is False and o["live_enabled"] is False
    assert o["real_orders"]==0 and o["gap_loss_can_exceed_20pct"] is True


def test_physical_original_v3_frozen_normal_and_cost_stress_results_unchanged():
    o=data()
    expected={
      "2025_Q1_PREVIOUSLY_INSPECTED":{
        "conservative":8.43707258,"stress":7.90278653,"severe":7.1014304},
      "2023_2026_CONTINUOUS_PREVIOUSLY_INSPECTED":{
        "conservative":343.66115005,"stress":320.11394615,
        "severe":285.97596337}
    }
    assert set(o["scopes"])==set(expected)
    for span,values in expected.items():
        for cost,pnl in values.items():
            assert o["scopes"][span]["profiles"][cost][
                "unmodified_original"]["net_pnl_usdt"]==pnl


def test_q1_no_trigger_all_profiles_exact_return_drawdown_fills():
    o=data()
    q1=o["scopes"]["2025_Q1_PREVIOUSLY_INSPECTED"]["profiles"]
    for cost,x in q1.items():
        original=x["unmodified_original"]
        guarded=x["causal_risk20"]
        assert original["net_pnl_usdt"]==guarded["net_pnl_usdt"]
        assert original["max_drawdown_pct"]==guarded["max_drawdown_pct"]
        assert original["fill_events"]==guarded["fill_events"]==9
        assert guarded["risk_audit"]["trigger_observed_after_close_utc"] is None
        assert guarded["risk_audit"]["first_actual_next_open_exit_utc"] is None
        assert guarded["risk_audit"]["forced_sell_fill_count"]==0


def test_three_year_normal_trigger_after_closed_bar_and_20pct_is_not_absolute_cap():
    o=data()
    p=o["scopes"]["2023_2026_CONTINUOUS_PREVIOUSLY_INSPECTED"]["profiles"]
    vals={"conservative":(152.86318294,20.16420603),
          "stress":(142.1645895,20.8678687),
          "severe":(133.67674702,21.00827844)}
    for cost,(pnl,dd) in vals.items():
        x=p[cost]["causal_risk20"]
        risk=x["risk_audit"]
        assert x["net_pnl_usdt"]==pnl
        assert x["max_drawdown_pct"]==dd
        assert x["max_drawdown_pct"]>20.0
        assert risk["halted_for_rest_of_period"] is True
        assert risk["trigger_observed_after_close_utc"] is not None
        assert risk["first_actual_next_open_exit_utc"] is not None
        assert risk["forced_sell_fill_count"]>=1
        assert risk["could_gap_beyond_threshold"] is True
        assert risk["no_reentry_after_exit"] is True
        assert risk["paper_eligible"] is False and risk["live_enabled"] is False
    assert p["conservative"]["causal_risk20"]["risk_audit"][
        "trigger_observed_after_close_utc"]=="2024-08-05T00:00:00+00:00"


def test_no_sharpe_or_return_claim_from_preinspected_threshold_choice():
    o=data()
    assert o["risk_policy_exact_frozen"]==pilot.RISK_POLICY
    assert o["threshold_selection_not_prospective_blind"] is True
    for scope in o["scopes"].values():
        assert scope["independent_500_usdt_period_reset"] is True
        for cost,x in scope["profiles"].items():
            assert len(x["independent_fifo_digest"])==64
            assert x["causal_risk20"]["fifo_matched_lot_segments"]>=0
            assert x["causal_risk20"]["fifo_winning_segments"]<=x[
                "causal_risk20"]["fifo_matched_lot_segments"]
            assert x["causal_risk20"]["risk_audit"][
                "closed_bar_threshold_fraction"]==0.20
