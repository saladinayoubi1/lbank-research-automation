"""Independent synthetic acceptance probes of 500-USDT shared-cash strategy gate."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pathlib import Path

from research import strategy_finder_shared_cash_physical as mod


def make(n=110):
    ts=pd.date_range("2025-01-01T00:15:00Z",periods=n,freq="15min")
    frames={}
    signal={}
    for symbol in mod.SYMBOLS:
        frames[symbol]=pd.DataFrame({
            "decision_at":ts,
            "open":np.full(n,100.),
            "high":np.full(n,101.),
            "low":np.full(n,99.),
            "close":np.full(n,100.),
            "atr":np.full(n,2.0),
        })
        signal[symbol]=np.zeros(n,dtype=np.bool_)
    return frames,signal


def test_no_signal_preserves_same_500_cash():
    f,s=make()
    result=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert result["net_pnl_usdt"]==0
    assert result["trades"]==0
    assert result["ending_shared_cash_usdt"]==500
    assert result["orders"]==0 and result["qualified"] is False


def test_causal_next_bar_open_is_exact_prior_close_utc_not_lookahead():
    f,s=make()
    s["BTCUSDT"][4]=True
    # Original signal closes at 1:15, next open is exactly 1:15.
    f["BTCUSDT"].loc[5,["open","high","low","close"]]=[101.,102.,100.,101.]
    result=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert result["trades"]==1
    entry=result["ledger"][0]
    instant=pd.Timestamp(entry["entry_open_ms"],unit="ms",tz="UTC")
    assert instant==pd.Timestamp(f["BTCUSDT"]["decision_at"].iloc[4])
    assert instant != pd.Timestamp(f["BTCUSDT"]["decision_at"].iloc[5])


def test_current_signal_never_fills_at_same_bar_close():
    f,s=make()
    s["BTCUSDT"][0]=True
    result=mod.replay_shared_cash(f,s,0,2,"conservative")
    assert result["ledger"][0]["entry_open_ms"]==int(pd.Timestamp(
        f["BTCUSDT"]["decision_at"].iloc[0]).value//10**6)


def test_same_open_priority_is_deterministic_and_cash_shared():
    f,s=make()
    s["ETHUSDT"][2]=True
    s["BTCUSDT"][2]=True
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["trades"]==1
    assert r["ledger"][0]["symbol"]=="BTCUSDT"
    assert r["denial_reasons"]["SAME_OPEN_LOWER_PRIORITY_PEER"]==1
    assert r["signals_due_at_next_open"]==2
    assert r["attempt_counts"]["admitted"]==1


def test_existing_open_position_blocks_future_signal_across_asset():
    f,s=make()
    s["BTCUSDT"][2]=True
    s["ETHUSDT"][3]=True
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["trades"]==1
    assert r["denial_reasons"]["SHARED_CASH_POSITION_OCCUPIED"]==1


def test_stop_priority_over_target_if_both_hit_same_entry_candle():
    f,s=make()
    s["BTCUSDT"][4]=True
    f["BTCUSDT"].loc[5,["high","low"]]=[140.,40.]
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["trades"]==1
    assert r["ledger"][0]["exit_reason"]=="STOP_FIRST_INTRABAR_BOTH"
    assert r["net_pnl_usdt"]<0


def test_physical_gap_below_stop_fills_at_worse_open():
    f,s=make()
    s["BTCUSDT"][2]=True
    f["BTCUSDT"].loc[4,["open","high","low","close"]]=[90.,92.,88.,91.]
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["ledger"][0]["exit_reason"]=="STOP_GAP_AT_WORSE_OPEN"
    assert r["ledger"][0]["exit_fill"]<r["ledger"][0]["stop"]


def test_predeclared_target_and_stress_cost():
    f,s=make()
    s["BTCUSDT"][4]=True
    f["BTCUSDT"].loc[6,"high"]=120.
    conservative=mod.replay_shared_cash(f,s,0,110,"conservative")
    stressed=mod.replay_shared_cash(f,s,0,110,"stress")
    assert conservative["ledger"][0]["exit_reason"]=="PRECOMMITTED_TARGET"
    assert conservative["net_pnl_usdt"]>stressed["net_pnl_usdt"]
    assert conservative["trades"]==1


def test_max_hold_exits_at_physical_open_not_close_hindsight():
    f,s=make()
    s["BTCUSDT"][2]=True
    f["BTCUSDT"].loc[67,["open","high","low","close"]]=[100.5,102.,99.5,101.]
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["ledger"][0]["exit_reason"]=="TIMEOUT_AT_PHYSICAL_NEXT_OPEN"
    assert r["ledger"][0]["exit_fill"]<100.5


def test_partition_end_close_explicitly_liquidates():
    f,s=make()
    s["BTCUSDT"][2]=True
    r=mod.replay_shared_cash(f,s,0,8,"conservative")
    assert r["ledger"][0]["exit_reason"]=="PARTITION_LAST_COMPLETED_CLOSE"
    assert r["trades"]==1


def test_old_partition_last_signal_cannot_steal_next_period_open():
    f,s=make()
    s["BTCUSDT"][7]=True
    r=mod.replay_shared_cash(f,s,8,50,"conservative")
    assert r["trades"]==0


def test_no_future_change_revises_earlier_closed_intent():
    f,s=make()
    s["BTCUSDT"][2]=True
    f["BTCUSDT"].loc[4,["high","low"]]=[150.,90.]
    a=mod.replay_shared_cash(f,s,0,20,"conservative")
    f["BTCUSDT"].loc[90,"high"]=999.
    b=mod.replay_shared_cash(f,s,0,20,"conservative")
    assert a==b


def test_mismatched_peer_grid_refused():
    f,s=make()
    f["ETHUSDT"].loc[10,"decision_at"]=pd.Timestamp(
        f["ETHUSDT"].loc[10,"decision_at"])+pd.Timedelta(minutes=15)
    with pytest.raises(mod.SharedCashDiagnosticError):
        mod.replay_shared_cash(f,s,0,110,"conservative")


def test_ohlc_corruption_refused():
    f,s=make()
    f["BTCUSDT"].loc[9,"low"]=120.
    with pytest.raises(mod.SharedCashDiagnosticError):
        mod.replay_shared_cash(f,s,0,110,"conservative")


def test_nonfinite_atr_for_one_signal_is_denied():
    f,s=make()
    s["BTCUSDT"][2]=True
    f["BTCUSDT"].loc[2,"atr"]=np.nan
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    assert r["trades"]==0
    assert r["denial_reasons"]["UNAVAILABLE_PRIOR_ATR"]==1


def test_frozen_profile_malformed_or_future_lookahead_rejected():
    f,s=make()
    with pytest.raises(mod.SharedCashDiagnosticError):
        mod.replay_shared_cash(f,s,0,110,"optimistic_zero_cost")
    with pytest.raises(mod.SharedCashDiagnosticError):
        mod.replay_shared_cash(f,s,-1,110,"conservative")


def test_six_partition_cells_but_no_demo_promotion_even_if_positive():
    f,s=make(n=120)
    for i in (3,44,82):
        s["BTCUSDT"][i]=True
        f["BTCUSDT"].loc[i+2,"high"]=130.
    result=mod.sidecar_summary(f,s)
    assert result["schema"]==mod.SCHEMA
    assert set(result["partitions"])=={
        "training","validation_already_inspected","historical_test_already_inspected"}
    for partition in result["partitions"].values():
        assert set(partition)=={"conservative","stress"}
        for profile in partition.values():
            assert profile["initial_shared_cash_usdt"]==500
            assert profile["orders"]==0
            assert profile["paper_eligible"] is False
    assert result["not_qualified_for_demo"] is True
    assert result["live_enabled"] is False
    assert len(result["result_digest"])==64


def test_float_physically_sized_and_fees_charge_both_sides():
    f,s=make()
    s["BTCUSDT"][3]=True
    f["BTCUSDT"].loc[5,"high"]=118.
    r=mod.replay_shared_cash(f,s,0,110,"conservative")
    one=r["ledger"][0]
    assert one["qty"]>0
    assert one["qty"]*one["entry_fill"]<=mod.MAX_GROSS_USDT+1e-6
    assert r["fees_paid_usdt"]>0
    assert r["net_pnl_usdt"]<r["ledger"][0]["qty"]*(one["exit_fill"]-one["entry_fill"])


def test_research_only_no_order_api_connector():
    source=Path(mod.__file__).read_text(encoding="utf-8")
    assert mod.LIVE_ENABLED is False
    assert mod.ORDER_ADAPTER is None
    assert "place_order(" not in source
    assert "create_order(" not in source
    assert mod.QUALIFIED is False
