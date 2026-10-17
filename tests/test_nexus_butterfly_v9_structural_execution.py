"""Synthetic-only Butterfly V9 structural entry/stop/target QA, no market tuning."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "research/butterfly_v9_structure_exit/plan_v9.py"
spec = importlib.util.spec_from_file_location("nexus_butterfly_v9_plan", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)
from nexus_causal_butterfly_features import ConfirmedPivot


def valid_pivots():
    prices = (100.0, 120.0, 104.28, 112.5, 94.6)
    return tuple(ConfirmedPivot(kind, idx, idx+3, price)
                 for kind, idx, price in zip(
                   ("low","high","low","high","low"),
                   (0,6,12,18,30), prices))


def plan(**overrides):
    p = {"closed_bar_index":34,"closed_open":96.7,"closed_close":97.0,
         "previous_close":96.4,"independently_closed_h1_vol_ok":True,
         "h1_context_last_closed_15m_index":31}
    p.update(overrides)
    return module.close_time_plan(valid_pivots(), **p)


def test_pinned_structural_levels_do_not_use_atr_or_future():
    a = plan()
    assert a["status"] == "CLOSED_BAR_PRECONDITIONS_PASS_NO_ORDER"
    assert a["stop_structural_1p414_XA"] == "91.72000000"
    assert a["target_first_0p382_CD"] == "101.43780000"
    assert a["D_right_confirmation_index"] == 33
    assert a["decision_closed_bar_index"] == 34
    assert a["allowed_hypothetical_next_open_index"] == 35
    assert a["order_enabled"] is False
    assert a["qualifies_for_demo"] is False
    assert a["plan_digest"] == module.digest({k:v for k,v in a.items() if k!="plan_digest"})


def test_next_open_costs_and_nominal_risk_budget_and_one_book_reference():
    a = plan()
    b = module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="conservative")
    assert b["status"] == "COST_AWARE_HYPOTHETICAL_ONLY_NO_ORDER"
    assert 0 < float(b["hypothetical_quantity"]) < 1
    assert 0 < float(b["hypothetical_buy_cash_spend"]) <= 50.00000001
    assert 0 < float(b["hypothetical_nominal_stop_loss_usdt"]) <= 2.50000001
    assert float(b["hypothetical_net_target_gain_usdt"]) > 0
    assert b["new_market_order"] is False
    assert b["paper_eligible"] is False
    assert b["live_enabled"] is False


def test_cost_stress_reduces_quoted_reward_without_changing_structural_levels():
    a = plan()
    conservative = module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="conservative")
    stress = module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="stress")
    assert conservative["linked_closed_plan_digest"] == stress["linked_closed_plan_digest"]
    assert conservative["estimated_stop_sell_fill_not_gap_guarantee"] != stress["estimated_stop_sell_fill_not_gap_guarantee"]
    assert float(stress["hypothetical_net_target_gain_usdt"]) < float(conservative["hypothetical_net_target_gain_usdt"])


@pytest.mark.parametrize("gap", [90,101.44,112.0])
def test_gap_through_stop_or_first_target_disallows_entry(gap):
    b=module.hypothetical_next_open(plan(),observed_bar_index=35,observed_open=gap,cost_profile="conservative")
    assert b["status"] == "INADMISSIBLE_NEXT_OPEN_OR_COSTS_NO_ORDER"
    assert b["hypothetical_quantity"] == "0.00000000"


@pytest.mark.parametrize("change",[
    {"closed_bar_index":35},
    {"closed_bar_index":32},
    {"closed_open":97.2,"closed_close":97.0},
    {"closed_close":96.0},
    {"independently_closed_h1_vol_ok":False},
])
def test_stale_and_unconfirmed_reversal_can_never_promote(change):
    if "closed_bar_index" in change:
        with pytest.raises(module.StructuralPlanError):
            plan(**change)
    else:
        a = plan(**change)
        assert a["status"] == "CLOSED_BAR_REJECT_NO_ORDER"
        b = module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="conservative")
        assert b["hypothetical_quantity"] == "0.00000000"


def test_future_open_not_a_close_time_argument_and_does_not_rewrite_plan():
    a=plan()
    bad=module.hypothetical_next_open(a,observed_bar_index=35,observed_open=90,cost_profile="conservative")
    ok=module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="conservative")
    assert bad["linked_closed_plan_digest"] == ok["linked_closed_plan_digest"]
    assert bad["status"] != ok["status"]


@pytest.mark.parametrize("tamper", [
    "changed_stop","forged_live","altered_next_index"
])
def test_mutated_signed_prior_closed_signal_refused(tamper):
    a=plan()
    if tamper=="changed_stop":
        a["stop_structural_1p414_XA"]="95.0"
    elif tamper=="forged_live":
        a["live_enabled"]=True
    else:
        a["allowed_hypothetical_next_open_index"]=36
    with pytest.raises(module.StructuralPlanError):
        module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="conservative")


def test_future_or_misaligned_next_open_refused():
    a=plan()
    for next_bar_index in (34,36,0):
        with pytest.raises(module.StructuralPlanError):
            module.hypothetical_next_open(a,observed_bar_index=next_bar_index,observed_open=97.3,cost_profile="conservative")
    with pytest.raises(module.StructuralPlanError):
        module.hypothetical_next_open(a,observed_bar_index=35,observed_open=97.3,cost_profile="invented")


def test_no_false_profit_extrapolation_and_immutable_old_protocol_boundaries():
    q=module.frozen_rulebook()
    assert q["no_unseen_market_data_used_for_selection"]
    assert q["not_a_backtest_or_measured_profit"]
    assert q["frozen_V8_not_modified"]
    assert q["frozen_Elliott_V117_not_modified"]
    assert q["no_automatic_demo_promotion"]
    assert q["contract_digest"] == module.digest({k:v for k,v in q.items() if k!="contract_digest"})
    assert "orders" not in [a for a in dir(module) if a=="submit_orders"]

@pytest.mark.parametrize("future_context",[32,33,34,35,30,-1])
def test_reject_future_stale_or_partial_h1_regime_context(future_context):
    with pytest.raises(module.StructuralPlanError,match="one-hour context"):
        plan(h1_context_last_closed_15m_index=future_context)


def test_registered_research_contract_equal_to_immutable_calculated_fields():
    register = ROOT / "docs/evidence/butterfly-v9-structural-prz-20261017/V9_PREREGISTERED_STRUCTURAL_STOP_TARGET.json"
    actual = json.loads(register.read_text(encoding="utf-8"))
    assert actual == module.frozen_rulebook()
    assert actual["contract_digest"] == module.digest({k:v for k,v in actual.items() if k!="contract_digest"})
    assert actual["PRZ_stop_XA_projection"] == "1.414"
    assert actual["CD_first_target_retracement"] == "0.382"
    assert actual["no_orders"] is True
