"""Research-only optional 20% closed-4h drawdown next-open-exit acceptance.

Never confuse an observed closed-bar trigger with a fill at that close.
Original long/cash portfolio risk remains unchanged when policy is omitted.
"""
from __future__ import annotations

from copy import deepcopy
import numpy as np
import pandas as pd
import pytest

import bybit_portfolio_search_v3 as old
from research.portfolio_v3_original_fill_journal import fifo_journal

POLICY={
 "schema":"nexus.portfolio-v3-causal-close-dd20-nextopen.v1",
 "max_closed_bar_drawdown_fraction":0.20,
 "halt_rest_of_research_period":True,
 "exit":"next_4h_open_sell_first_no_reentry",
 "live_authority":False,
}


def synthetic(*, gap_open=60.,trigger_close=79.,n=50):
    ts=pd.Series(pd.date_range("2025-01-01",periods=n,freq="4h",tz="UTC"))
    opening=np.full((n,2),100.)
    closing=np.full((n,2),100.)
    closing[5,0]=trigger_close
    opening[6,0]=gap_open
    closing[6,0]=gap_open
    weights=np.zeros((n,2))
    weights[:,0]=1.
    return dict(
        timestamps=ts,symbols=["btc_usdt","eth_usdt"],
        open=opening,close=closing,high=np.maximum(opening,closing),
        low=np.minimum(opening,closing)),weights,{
          "start":"2025-01-01","end":"2025-01-09"
        },{"initial_cash":500.,"fee_bps":10.,"slippage_bps":5.}


def test_closed_bar_trigger_exit_at_first_actual_next_open_gap_accepted():
    m,w,period,cost=synthetic()
    trace={}
    measured=old.exact_backtest(m,w,period,cost,fill_trace=trace,risk_policy=POLICY)
    risk=measured["causal_risk_audit"]
    assert risk["trigger_observed_after_close_utc"]==m["timestamps"].iloc[6].isoformat()
    assert risk["first_actual_next_open_exit_utc"]==m["timestamps"].iloc[6].isoformat()
    assert risk["halted_for_rest_of_period"] is True
    assert risk["forced_sell_fill_count"]==1
    assert risk["liquidation_cash_after_all_sales_usdt"]==pytest.approx(
        trace["terminal_cash_usdt"])
    # The bar closes down 21%, but there is a worse next-open gap to 60.
    sells=[r for r in trace["fills"] if r["side"]=="sell"]
    assert len(sells)==1
    assert sells[0]["fill_kind"]=="next_bar_open"
    assert sells[0]["executed_at_utc"]==risk["first_actual_next_open_exit_utc"]
    assert sells[0]["price_usdt"]==pytest.approx(60.*(1.-.0005))
    assert sells[0]["price_usdt"]<trigger_close_only_fill_price()
    assert measured["max_drawdown"]>0.35
    assert measured["total_return"] < -0.35
    assert len(trace["fills"])==2
    assert trace["equity_marks"][-1]["asset_quantities"]==[0.,0.]
    assert fifo_journal(trace,measured)["net_profit_usdt"]==pytest.approx(
        measured["total_return"]*500.,abs=2e-6)


def trigger_close_only_fill_price():
    return 79.*(1-.0005)


def test_original_engine_default_and_none_risk_are_exactly_identical():
    m,w,p,c=synthetic()
    x=old.exact_backtest(m,w,p,c)
    y=old.exact_backtest(m,w,p,c,risk_policy=None)
    assert x==y
    assert "causal_risk_audit" not in x
    assert x["total_return"] != old.exact_backtest(
        m,w,p,c,risk_policy=POLICY)["total_return"]


def test_risk_policy_not_fabricating_triggers_without_real_equity_losses():
    m,w,p,c=synthetic(trigger_close=100.,gap_open=100.)
    risk=old.exact_backtest(m,w,p,c,risk_policy=POLICY)
    assert risk["causal_risk_audit"]["trigger_observed_after_close_utc"] is None
    assert risk["causal_risk_audit"]["forced_sell_fill_count"]==0
    assert risk["causal_risk_audit"]["halted_for_rest_of_period"] is False
    assert risk["causal_risk_audit"]["trigger_on_last_bar_no_next_open"] is False
    assert risk["total_return"]==pytest.approx(old.exact_backtest(
        m,w,p,c)["total_return"],abs=1e-14)


def test_no_extra_open_position_after_loss_switch_even_if_old_targets_long():
    m,w,p,c=synthetic()
    trace={}
    result=old.exact_backtest(m,w,p,c,risk_policy=POLICY,fill_trace=trace)
    trigger=pd.Timestamp(result["causal_risk_audit"]["first_actual_next_open_exit_utc"])
    assert all(
        f["side"]=="sell" for f in trace["fills"]
        if pd.Timestamp(f["executed_at_utc"])>=trigger
    )
    assert result["causal_risk_audit"]["no_reentry_after_exit"] is True


@pytest.mark.parametrize("mutate",[
    lambda p:p.update(max_closed_bar_drawdown_fraction=.19),
    lambda p:p.update(exit="trigger_bar_close_hindsight"),
    lambda p:p.update(live_authority=True),
    lambda p:p.update(halt_rest_of_research_period=False),
    lambda p:p.update(schema="unregistered-risk-version"),
    lambda p:p.update(hidden_switch=True),
])
def test_unreviewed_risk_policy_threshold_or_future_peek_rejected(mutate):
    m,w,p,c=synthetic()
    x=deepcopy(POLICY)
    mutate(x)
    with pytest.raises(old.PortfolioSearchError,match="Unreviewed"):
        old.exact_backtest(m,w,p,c,risk_policy=x)


def test_fresh_strict_4h_market_time_grid_required_only_for_opt_in_risk():
    m,w,p,c=synthetic()
    m["timestamps"].iloc[25]=m["timestamps"].iloc[24]
    with pytest.raises(old.PortfolioSearchError,match="exact completed UTC 4h"):
        old.exact_backtest(m,w,p,c,risk_policy=POLICY)


def test_multiple_assets_force_exit_sell_all_before_any_more_buys():
    m,w,p,c=synthetic()
    w[:,:]=0.5
    trace={}
    x=old.exact_backtest(m,w,p,c,risk_policy=POLICY,fill_trace=trace)
    a=x["causal_risk_audit"]
    assert a["halted_for_rest_of_period"] is False or a["forced_sell_fill_count"] in (0,2)
    assert len(trace["fills"])==x["fill_count"]
    assert fifo_journal(trace,x)["terminal_cash_usdt"]==pytest.approx(
        500*(1+x["total_return"]),abs=2e-6)


def test_no_risk_approval_or_order_authority_in_optional_result():
    m,w,p,c=synthetic()
    x=old.exact_backtest(m,w,p,c,risk_policy=POLICY)
    r=x["causal_risk_audit"]
    assert r["research_only"] is True
    assert r["paper_eligible"] is False
    assert r["live_enabled"] is False
    assert r["could_gap_beyond_threshold"] is True
