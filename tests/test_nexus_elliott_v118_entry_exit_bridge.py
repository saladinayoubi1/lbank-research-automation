"""Adversarial V118 causal Wave1-break/Wave2-stop physical diagnostics."""
from __future__ import annotations
from dataclasses import replace
from decimal import Decimal
import importlib
from pathlib import Path
import pytest

from research.elliott_v118_entry_exit_bridge import bridge_v118 as v118
from research.elliott_v102_bybit_intake import intake_v102 as v102
from research.elliott_v99_causal_scale import scale_v99 as v99

M=v118.MINUTE
START=1719792000000


def candle(i:int,op="109",hi="109.5",lo="108.5",cl="109")->v102.Candle:
    return v102.Candle(START+i*M,*(Decimal(x) for x in
       (op,hi,lo,cl,"10","100")))


def two_sources(n=300):
    left=[candle(i) for i in range(n)]
    # First after W2 confirmation at index 11: close crosses W1=110.
    left[10]=candle(10,op="109",hi="109.5",lo="108",cl="109")
    left[11]=candle(11,op="109",hi="111.5",lo="108",cl="111")
    left[12]=candle(12,op="111.2",hi="112",lo="110",cl="111")
    right=[candle(i) for i in range(n)]
    return {"BTCUSDT":left,"ETHUSDT":right}


def six():
    kinds=("HIGH","LOW","HIGH","LOW","HIGH","LOW")
    prices=("104","98","103","100","110","105")
    return [v99.ObservedSwing(
        kind=k,center_ms=START+i*2*M,
        confirmed_ms=START+(i*2+1)*M,
        center_close=Decimal(p),confirm_close=Decimal(p),
        center_index=i*2,confirmed_index=i*2+1,
    ) for i,(k,p) in enumerate(zip(kinds,prices))]


def candidate(sym="BTCUSDT",ordinal=1):
    c=two_sources()[sym]
    result=v118.find_first_breakout(sym,ordinal,six(),START+11*M,c)
    assert result["classification"]=="CLOSED_WAVE1_BREAKOUT_NEXT_OPEN"
    return result


def test_unchanged_source_w2_confirmation_signal_at_close_next_open():
    intent=candidate()
    assert intent["decision_ms"]==START+11*M
    assert intent["signal_closed_ms"]==START+12*M
    assert intent["entry_open_ms"]==START+12*M
    assert intent["entry_index"]==12
    assert Decimal(intent["wave2_stop"])==Decimal(105)
    assert Decimal(intent["wave1"])==Decimal(110)


def test_future_prices_cannot_change_signal_or_original_stop():
    original=two_sources()
    baseline=v118.find_first_breakout("BTCUSDT",1,six(),START+11*M,original["BTCUSDT"])
    changed=two_sources()
    changed["BTCUSDT"][14]=candle(14,"300","400","106","250")
    changed["BTCUSDT"][200]=candle(200,"1000","1000","900","950")
    assert v118.find_first_breakout("BTCUSDT",1,six(),START+11*M,changed["BTCUSDT"])==baseline


def test_w2_origin_breach_preentry_prevents_favorable_same_bar_close():
    bars=two_sources()["BTCUSDT"]
    bars[11]=candle(11,"109","113","104","112")
    result=v118.find_first_breakout("BTCUSDT",1,six(),START+11*M,bars)
    assert result["classification"]=="WAVE2_INVALIDATED_BEFORE_ENTRY"


def test_spot_bearish_abstains_without_short():
    points=six()
    points[3]=replace(points[3],kind="HIGH")
    result=v118.find_first_breakout("BTCUSDT",1,points,START+11*M,two_sources()["BTCUSDT"])
    assert result["classification"]=="BEARISH_SPOT_NO_SHORT"


def test_unchanged_breakout_absence_is_not_a_position():
    bars=two_sources()["BTCUSDT"]
    bars[11]=candle(11,"109","109.5","108","109")
    bars[12]=candle(12,"109","109.5","108","109")
    result=v118.find_first_breakout("BTCUSDT",1,six(),START+11*M,bars)
    assert result["classification"] in (
        "NO_CLOSED_WAVE1_BREAKOUT_WITHIN_240M",
        "RIGHT_CENSORED_NO_COMPLETE_240M_BREAKOUT_WINDOW",
    )


def test_stop_first_with_same_entry_bar_target_touch():
    data=two_sources()
    # After buying at index12, both stop and 2R target seen; stop wins.
    data["BTCUSDT"][12]=candle(12,op="111.2",hi="140",lo="100",cl="120")
    result=v118.replay_proposals([candidate()],data,"conservative")
    assert result["admitted_round_trips"]==1
    trade=result["original_trade_events"][0]
    assert trade["exit_reason"]=="STOP_FIRST_SAME_BAR_IF_TARGET_ALSO_HIT"
    assert Decimal(trade["net_pnl_usdt"])<0
    assert Decimal(trade["entry_cash_cost"])<=Decimal("250.5")
    assert Decimal(trade["qty"])>0
    assert result["paper_eligible"] is False


def test_stop_only_is_not_falsely_called_ambiguous_stop_target_bar():
    data=two_sources()
    data["BTCUSDT"][12]=candle(12,op="111.2",hi="112",lo="104",cl="108")
    result=v118.replay_proposals([candidate()],data,"conservative")
    assert result["admitted_round_trips"]==1
    trade=result["original_trade_events"][0]
    assert trade["exit_reason"]=="STRUCTURE_STOP_ONLY"
    assert Decimal(trade["net_pnl_usdt"])<0


def test_gap_through_stop_executes_worse_open():
    data=two_sources()
    data["BTCUSDT"][12]=candle(12,op="104",hi="112",lo="100",cl="111")
    intent=candidate()
    intent["mid_open"]="104"
    result=v118.replay_proposals([intent],data,"conservative")
    assert result["admitted_round_trips"]==0
    assert result["all_denials"][0]["why"]=="ENTRY_BELOW_STRUCTURE_STOP"


def test_real_gap_after_entry_worse_than_protective_stop():
    data=two_sources()
    data["BTCUSDT"][13]=candle(13,op="102",hi="103",lo="99",cl="101")
    result=v118.replay_proposals([candidate()],data,"conservative")
    tr=result["original_trade_events"][0]
    assert tr["exit_reason"]=="GAP_THROUGH_STOP_AT_WORSE_OPEN"
    assert Decimal(tr["exit_fill"])<Decimal(tr["hard_stop"])


def test_physical_target_and_fee_slippage_adverse():
    data=two_sources()
    data["BTCUSDT"][13]=candle(13,"112","130","111","124")
    v=v118.replay_proposals([candidate()],data,"conservative")
    stress=v118.replay_proposals([candidate()],data,"stress")
    assert v["admitted_round_trips"]==stress["admitted_round_trips"]==1
    assert Decimal(stress["net_pnl_usdt"])<Decimal(v["net_pnl_usdt"])
    assert v["original_trade_events"][0]["exit_reason"]=="TARGET_LIMITED_TO_PREDECLARED_2R"


def test_one_shared_cash_account_simultaneous_signals_denied():
    data=two_sources()
    data["BTCUSDT"][13]=candle(13,"112","130","111","124")
    data["ETHUSDT"][13]=candle(13,"112","130","111","124")
    b=candidate("BTCUSDT",1)
    e=replace if False else dict(b, symbol="ETHUSDT",id="ETHUSDT-1")
    a=v118.replay_proposals([e,b],data,"conservative")
    assert a["admitted_round_trips"]==1
    assert a["denied_after_signal_count"]==1
    assert a["all_denials"][0]["why"]=="ONE_SHARED_CASH_POSITION_ALREADY_OPEN"


@pytest.mark.parametrize("change",["same_open","earlier_signal","wrong_price","bad_symbol","duplicate"])
def test_anti_lookahead_and_identity_tamper_are_rejected(change):
    data=two_sources()
    x=candidate()
    if change=="same_open":
        x["entry_open_ms"]-=M
    elif change=="earlier_signal":
        x["signal_closed_ms"]-=M
    elif change=="wrong_price":
        x["mid_open"]="12345"
    elif change=="bad_symbol":
        x["symbol"]="LBank"
    elif change=="duplicate":
        with pytest.raises(v118.ElliottV118Error):
            v118.replay_proposals([x,x],data,"conservative")
        return
    with pytest.raises(v118.ElliottV118Error):
        v118.replay_proposals([x],data,"conservative")


def test_frozen_no_live_order_and_no_v117_source():
    p=Path(v118.__file__).read_text("utf-8")
    assert v118.ENTRY_SIGNAL is False
    assert v118.LIVE_ENABLED is False
    assert v118.PAPER_ELIGIBLE is False
    assert v118.ORDER_ADAPTER is None
    assert v118.PROSPECTIVE_V117_UNTOUCHED is True
    assert "requests.post(" not in p
    assert "api.bybit.com" not in p


def test_nonfinite_or_nonphysical_ohlc_rejected_by_original_source_validator():
    data=two_sources()
    data["BTCUSDT"][30]=replace(data["BTCUSDT"][30],high=Decimal("100"))
    with pytest.raises(ValueError):
        v118.replay_proposals([candidate()],data,"conservative")


def test_right_censored_trade_does_not_claim_realized_pnl():
    data=two_sources(n=30)
    x=candidate()
    result=v118.replay_proposals([x],data,"conservative")
    assert result["status"]=="INCOMPLETE_SOURCE_WITH_OPEN_POSITION_NO_NET_PNL"
    assert result["net_pnl_usdt"] is None
