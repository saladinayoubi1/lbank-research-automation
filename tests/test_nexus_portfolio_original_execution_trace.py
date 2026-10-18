"""Verify native v3 trace never changes trades, fees, cash or risk metrics."""
from __future__ import annotations

from copy import deepcopy
import json

import numpy as np
import pandas as pd
import pytest

import bybit_portfolio_search_v3 as old
from research.portfolio_v3_original_fill_journal import fifo_journal, FillJournalError


def made_market(n=90):
    ts=pd.Series(pd.date_range("2025-01-01",periods=n,freq="4h",tz="UTC"))
    x=np.arange(n,dtype=float)
    o=np.column_stack((100+np.sin(x/5)*3+x*0.1, 75+np.cos(x/7)*2-x*0.04))
    c=o*np.column_stack((1+0.005*np.sin(x/3),1-0.004*np.cos(x/4)))
    return {"timestamps":ts,"symbols":["btc_usdt","eth_usdt"],
            "open":o,"close":c,"high":np.maximum(o,c)*1.01,
            "low":np.minimum(o,c)*.99}


def study():
    m=made_market()
    weights=np.zeros((len(m["timestamps"]),2))
    weights[:25,0]=1.0
    weights[25:45,0]=.25
    weights[25:45,1]=.5
    weights[45:65,1]=1.0
    weights[65:,0]=.25
    weights[65:,1]=.25
    profile={"initial_cash":500.0,"fee_bps":10.0,"slippage_bps":5.0}
    dates={"start":"2025-01-01","end":"2025-01-16"}
    return m,weights,dates,profile


def test_original_default_core_no_fill_tape_behavior_change():
    m,w,d,p=study()
    basic=old.exact_backtest(m,w,d,p)
    traced={}
    observed=old.exact_backtest(m,w,d,p,fill_trace=traced)
    assert observed==basic
    assert len(traced["fills"])==basic["fill_count"]
    assert len(traced["equity_marks"])==90
    assert traced["initial_cash_usdt"]==500
    assert traced["terminal_cash_usdt"]==pytest.approx(500*(1+basic["total_return"]))
    journal=fifo_journal(traced,basic)
    assert journal["closed_fifo_lot_segments"]>=1
    assert journal["exact_original_buy_sell_fill_events"]==basic["fill_count"]
    assert journal["total_fees_usdt"]==pytest.approx(basic["total_fees"],abs=2e-6)
    assert journal["net_profit_usdt"]==pytest.approx(500*basic["total_return"],abs=2e-6)
    assert journal["live_enabled"] is False and journal["real_orders"]==0


def test_stress_execution_and_scheduled_mask_same_old_metrics():
    m,w,d,p=study()
    mask=np.arange(len(w))%6==0
    for fee,slip in ((10,5),(15,10),(25,15)):
        cost={**p,"fee_bps":fee,"slippage_bps":slip}
        orig=old.exact_backtest(m,w,d,cost,rebalance_mask=mask)
        trace={}
        rec=old.exact_backtest(m,w,d,cost,rebalance_mask=mask,fill_trace=trace)
        assert rec==orig
        rows=fifo_journal(trace,rec)
        assert rows["net_profit_usdt"]==pytest.approx(500*rec["total_return"],abs=2e-6)
        assert rows["observed_max_drawdown_pct"]==pytest.approx(rec["max_drawdown"]*100,abs=1e-7)
        assert all(q==0 for q in trace["terminal_quantities"])


def test_repeated_trace_cannot_mix_two_financial_eras():
    m,w,d,p=study()
    t={}
    old.exact_backtest(m,w,d,p,fill_trace=t)
    with pytest.raises(old.PortfolioSearchError,match="fresh empty"):
        old.exact_backtest(m,w,d,p,fill_trace=t)
    with pytest.raises(old.PortfolioSearchError,match="fresh empty"):
        old.exact_backtest(m,w,d,p,fill_trace={"fills":[]})


def test_trace_requires_actual_utc_grid_and_original_symbol_names():
    m,w,d,p=study()
    bad=deepcopy(m)
    bad["timestamps"].iloc[25]=bad["timestamps"].iloc[24]
    with pytest.raises(old.PortfolioSearchError,match="4h"):
        old.exact_backtest(bad,w,d,p,fill_trace={})
    bad=deepcopy(m)
    bad.pop("symbols")
    with pytest.raises(old.PortfolioSearchError,match="Exact source"):
        old.exact_backtest(bad,w,d,p,fill_trace={})


def test_short_or_oversold_injected_fill_is_detected():
    m,w,d,p=study()
    tape={}
    out=old.exact_backtest(m,w,d,p,fill_trace=tape)
    corrupted=deepcopy(tape)
    entry=next(x for x in corrupted["fills"] if x["side"]=="sell")
    entry["quantity"]=entry["quantity"]*2
    with pytest.raises(FillJournalError):
        fifo_journal(corrupted,out)


def test_injected_cash_balance_and_missing_fees_fail_closed():
    m,w,d,p=study()
    tape={}
    out=old.exact_backtest(m,w,d,p,fill_trace=tape)
    c=deepcopy(tape)
    c["fills"][0]["cash_after_usdt"]+=1
    with pytest.raises(FillJournalError,match="cash or asset inventory"):
        fifo_journal(c,out)
    c=deepcopy(tape)
    c["fills"][0]["fee_usdt"]=0.0
    with pytest.raises(FillJournalError):
        fifo_journal(c,out)


def test_tampered_mark_to_market_drawdown_fails_closed():
    m,w,d,p=study()
    tape={}
    out=old.exact_backtest(m,w,d,p,fill_trace=tape)
    c=deepcopy(tape)
    c["equity_marks"][45]["equity_usdt"]*=0.5
    with pytest.raises(FillJournalError,match="drawdown"):
        fifo_journal(c,out)


def test_terminal_liquidation_is_labeled_close_not_next_bar_open():
    m,w,d,p=study()
    tape={}
    orig=old.exact_backtest(m,w,d,p,fill_trace=tape)
    terminal=[f for f in tape["fills"] if f["fill_kind"]=="terminal_bar_close"]
    assert terminal
    assert all(f["side"]=="sell" for f in terminal)
    assert all(pd.Timestamp(f["executed_at_utc"]) ==
               pd.Timestamp(f["source_bar_open_utc"])+pd.Timedelta(hours=4)
               for f in terminal)
    assert fifo_journal(tape,orig)["closed_fifo_lot_segments"]>0


def test_cash_only_empty_fill_journal_is_not_fabricated_trade_count():
    m,w,d,p=study()
    cash=np.zeros_like(w)
    tape={}
    metrics=old.exact_backtest(m,cash,d,p,fill_trace=tape)
    ledger=fifo_journal(tape,metrics)
    assert ledger["exact_original_buy_sell_fill_events"]==0
    assert ledger["closed_fifo_lot_segments"]==0
    assert ledger["mean_net_pnl_per_fifo_matched_segment_usdt"] is None
    assert ledger["net_profit_usdt"]==pytest.approx(0,abs=1e-9)
    assert ledger["total_fees_usdt"]==0
