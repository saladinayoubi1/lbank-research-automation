"""Wave2 support/retest research V119: isolated anti-lookahead and cash tests."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from research.elliott_v119_wave2_support import retest_v119 as v


def bars(n=250):
    t=pd.Series(pd.date_range("2025-01-01",periods=n,freq="15min",tz="UTC"))
    a={s:{f:np.full(n,105.,dtype=float) for f in (
        "open","high","low","close")} for s in v.SYMBOLS}
    for s in v.SYMBOLS:
        a[s]["high"][:]=106
        a[s]["low"][:]=104
    return a,t


def intent(sym="BTC",idx=18):
    return {
        "symbol":sym,"pivot_w0_center":0,"pivot_w1_center":6,
        "pivot_w2_center":10,"w2_known_after_closed_index":13,
        "retest_completed_index":idx-2,
        "reclaim_completed_index":idx-1,
        "entry_index":idx,"w0_physical_low":90.0,
        "w1_physical_high":120.0,"w2_physical_low":100.0,
    }


def test_historical_scope_cost_model_no_exchange_trading():
    assert v.SHAS["BTC"]!=v.SHAS["ETH"]
    assert v.LIVE_ENABLED is False
    assert v.PAPER_ELIGIBLE is False
    assert v.AUTOMATIC_DEMO_PROMOTION is False
    assert v.ENTRY_SIGNAL is False
    assert v.CASH==500.0
    assert v.PROFILES=={"conservative":(10.,5.),"stress":(25.,15.)}


def test_strict_physical_pivot_right_confirmation_and_dual_refusal():
    hi=np.full(24,106.)
    lo=np.full(24,104.)
    hi[8]=110
    lo[16]=100
    output=v.confirmed_pivots(hi,lo)
    assert (11,8,"HIGH",110.) in output
    assert (19,16,"LOW",100.) in output
    assert all(t[0]==t[1]+3 for t in output)
    hi[16]=120
    output2=v.confirmed_pivots(hi,lo)
    assert not any(z[1]==16 for z in output2)


def test_future_price_changes_do_not_rewrite_confirmed_past():
    hi=np.full(50,106.)
    lo=np.full(50,104.)
    hi[8]=110
    lo[16]=100
    original=[p for p in v.confirmed_pivots(hi,lo) if p[0]<25]
    hi[29:]*=2
    lo[29:]/=2
    changed=[p for p in v.confirmed_pivots(hi,lo) if p[0]<25]
    assert original==changed


def test_wave2_retest_reclaim_is_distinct_from_wave1_breakout(monkeypatch):
    data,t=bars()
    x=data["BTC"]
    x["low"][14]=102
    x["close"][14]=104
    x["high"][14]=106
    x["low"][15]=103
    x["open"][15]=103
    x["close"][15]=107
    x["high"][15]=108
    original=((10,7,"LOW",90.),(12,9,"HIGH",120.),(13,10,"LOW",100.))
    monkeypatch.setattr(v,"confirmed_pivots",lambda h,l:list(original))
    found,counts=v.support_retest_signals(x,10,80,"BTC")
    assert counts["source_confirmed_triplets"]==1
    assert counts["physical_support_reclaim_signals"]==1
    assert len(found)==1
    assert found[0]["reclaim_completed_index"]==15
    assert found[0]["entry_index"]==16
    assert found[0]["w1_physical_high"]==120
    assert x["close"][15]<120
    x["high"][200]=5000
    later,_=v.support_retest_signals(x,10,80,"BTC")
    assert later==found


def test_swept_support_preentry_abstains(monkeypatch):
    data,t=bars()
    x=data["BTC"]
    x["low"][14]=99.9
    monkeypatch.setattr(v,"confirmed_pivots",lambda h,l:[
        (10,7,"LOW",90.),(12,9,"HIGH",120.),(13,10,"LOW",100.)])
    found,counts=v.support_retest_signals(x,10,80,"BTC")
    assert not found
    assert counts["physical_wave2_support_failed_before_entry"]==1


def test_strict_triplet_no_pruning_same_kind(monkeypatch):
    data,t=bars()
    monkeypatch.setattr(v,"confirmed_pivots",lambda h,l:[
        (10,7,"LOW",90.),(11,8,"LOW",89.),(12,9,"HIGH",120.),
        (13,10,"LOW",100.)])
    found,counts=v.support_retest_signals(data["BTC"],10,80,"BTC")
    assert not found
    assert counts["source_confirmed_triplets"]==2
    assert counts["non_LHL_source_triplets"]==1
    assert counts["no_retest_reclaim_within_48_completed_bars"]==1


def test_fee_stress_reduces_exact_identical_winning_trade():
    d,t=bars()
    d["BTC"]["high"][20]=125.
    a=v.replay(d,t,[intent()],10,140,"conservative")
    b=v.replay(d,t,[intent()],10,140,"stress")
    assert a["round_trips"]==b["round_trips"]==1
    assert a["trades"][0]["cause"]=="PRECOMMITTED_TARGET"
    assert a["net_pnl_usdt"]>b["net_pnl_usdt"]
    assert a["trades"][0]["entry_cash_spend_usdt"]<=251
    assert a["positive_net_trades"]==1


def test_entry_bar_both_high_and_low_stop_first():
    d,t=bars()
    d["BTC"]["low"][18]=90
    d["BTC"]["high"][18]=130
    r=v.replay(d,t,[intent()],10,140,"conservative")
    assert r["round_trips"]==1
    assert r["trades"][0]["cause"]=="STOP_FIRST_AMBIGUOUS"
    assert r["net_pnl_usdt"]<0


def test_ordinary_stop_not_mislabeled_ambiguous():
    d,t=bars()
    d["BTC"]["low"][18]=90
    r=v.replay(d,t,[intent()],10,140,"conservative")
    assert r["trades"][0]["cause"]=="STRUCTURE_STOP_ONLY"


def test_gap_after_entry_executes_at_worse_open():
    d,t=bars()
    d["BTC"]["open"][19]=95
    d["BTC"]["low"][19]=90
    d["BTC"]["high"][19]=106
    r=v.replay(d,t,[intent()],10,140,"conservative")
    assert r["trades"][0]["cause"]=="STRUCTURE_STOP_GAP"
    assert r["net_pnl_usdt"]<0


def test_synthetic_censors_at_partition_end_and_no_future_profit():
    d,t=bars()
    r=v.replay(d,t,[intent()],10,120,"conservative")
    assert r["trades"][0]["cause"]=="TIMEOUT_OR_PARTITION_END_OPEN"
    assert r["trades"][0]["exit_index"]==18+v.MAX_HOLD


def test_shared_cash_no_two_simultaneous_long_legs():
    d,t=bars()
    d["BTC"]["high"][20]=125
    d["ETH"]["high"][20]=125
    r=v.replay(d,t,[intent("BTC"),intent("ETH")],10,140,"conservative")
    assert r["round_trips"]==1
    assert r["denied_after_signal"]["cash_book_already_occupied"]==1
    assert r["ending_cash_usdt"]>=0


def test_no_entry_below_stop_or_above_w1():
    d,t=bars()
    d["BTC"]["open"][18]=121
    r=v.replay(d,t,[intent()],10,140,"conservative")
    assert r["round_trips"]==0
    assert r["denied_after_signal"]["unfavorable_next_open_or_invalid_original_stop"]==1


def test_reject_wrong_causal_order_of_retest():
    d,t=bars()
    p=intent()
    p["reclaim_completed_index"]=p["entry_index"]
    with pytest.raises(v.V119Error,match="future leakage"):
        v.replay(d,t,[p],10,140,"conservative")


def test_reject_malformed_pivot_grid():
    with pytest.raises(v.V119Error):
        v.confirmed_pivots(np.array([100.,np.nan,110.,111.,100.,100.,100.]),
                           np.ones(7))


def test_reject_unpinned_file_without_attempting_market_download(tmp_path):
    p=tmp_path/"source.parquet"
    p.write_bytes(b"not an authenticated market archive")
    with pytest.raises(v.V119Error,match="SHA256"):
        v.verified_frame(p,"BTC")


def test_no_order_api_or_live_paths():
    code=Path(v.__file__).read_text(encoding="utf-8")
    assert "requests.post(" not in code
    assert "create_order(" not in code
    assert "live_enabled" in code
    assert "automatic_demo_promotion" in code
