"""Future-only MR40 ATR14×2 initial protective research candidate.

All outputs are hypothetical Spot quote geometry or bar-LOW touch observations,
never order instructions or actual stop fills. Does not change the original
MR40 strategy, Bybit Paper state, or historical entry-stop experiments.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from decimal import Decimal as D, localcontext
from pathlib import Path

from research.nexus_mr40_independent_closed_signal_v1 import STEP,canon

SCHEMA="nexus.mr40.prospective_prearm_atr14x2_research_protocol.v1"
ATR_WINDOW=14
ATR_MULTIPLIER=D("2")
DAY_FIRST="2026-10-23"
DAY_LAST_EXCLUSIVE="2026-12-23"
REFERENCE_CASH=D("500")
BUDGETS=(D("1"),D("2"))
COST_PROFILES={
    "VIP0_FEE_ONLY":(D("0.001"),D("0")),
    "VIP0_PLUS_0_1PCT_EACH_SIDE_SLIP_STRESS":(D("0.001"),D("0.001"))
}
FROZEN_SOURCE="a458d9f83df633df8ee5cab5f2a19de41c4c79c61185b5abd258fdefa80d575a"
OCT22_ARCHIVE="9591b0ccf534810939771e59ec95d6dbab4f978a72c57f86b2b332ef4cb84587"
OCT22_AUDIT="ea5f020264cb3e307bc142f22a9736c8c5afdd5df16fa9615927f887384c099c"


def verify_protocol(data):
    m=data["market"];c=data["candidate"];e=data["prospective_evaluation"];s=data["safety"]
    profiles={q["id"]:(D(q["fee_each_side"]),D(q["slippage_each_side"])) for q in data["cost_scenarios"]}
    if (data.get("schema")!=SCHEMA or m["venue"]!="Bybit" or m["symbol"]!="BTCUSDT"
        or m["category"]!="spot" or m["interval_minutes"]!=240
        or m["first_unseen_utc_day"]!=DAY_FIRST
        or m["end_exclusive_utc"]!=DAY_LAST_EXCLUSIVE
        or m["frozen_8514_rows_sha256"]!=FROZEN_SOURCE
        or m["verified_oct22_official_spot_gzip_sha256"]!=OCT22_ARCHIVE
        or m["verified_oct22_WS_parity_result_sha256"]!=OCT22_AUDIT
        or c["id"]!="PREARM_ATR14_X2_CLOSED_SIGNAL"
        or c["atr_window"]!=ATR_WINDOW
        or D(c["atr_multiplier"])!=ATR_MULTIPLIER
        or c["atr_aggregation"]!="arithmetic mean of last 14 fully CLOSED 4h true ranges including completed signal bar and never entry bar"
        or c["active_immediately_after_hypothetical_entry"] is not True
        or c["ratchet_after_profit"] is not False
        or data["comparator"]["id"]!="UNCHANGED_MR40_BASELINE_NATURAL_EXIT"
        or D(data["reference"]["capital_USDT"])!=REFERENCE_CASH
        or tuple(D(x) for x in data["reference"]["diagnostic_risk_budgets_pct_of_cash"])!=BUDGETS
        or profiles!=COST_PROFILES
        or e["new_signal_entries_only_from"]!="2026-10-23T00:00:00Z"
        or e["num_completed_nonoverlapping_trades_minimum_for_directional_screen"]!=12
        or any(s[k] is not False for k in ("private_api","paper_modified","live","merge","promote"))
        or s["no_orders"] is not True or s["no_scheduler"] is not True):
        raise ValueError("frozen_prearm_ATR_prospective_protocol_drift")
    return True


def _market_ohlc(bar):
    if type(bar[0]) is not int or bar[0]%STEP:
        raise ValueError("invalid_4h_bar_clock")
    a=[D(str(x)) for x in bar[1:]]
    if len(a)!=5 or not all(x.is_finite() for x in a):
        raise ValueError("invalid_price_or_volume")
    op,hi,lo,cl,vol=a
    if min(op,hi,lo,cl)<=0 or vol<0 or hi<max(op,cl) or lo>min(op,cl):
        raise ValueError("bad_candle_envelope")
    return op,hi,lo,cl,vol


def atr14_from_confirmed_signal_history(closed_bars):
    """Only prior 15 FULL candles, including signal bar; entry candle excluded.

    Last 14 true ranges each use the previous fully closed candle close.
    A 15th prior candle is required for TR of the oldest of those 14.
    """
    if len(closed_bars)<ATR_WINDOW+1:
        raise ValueError("at_least_15_verified_completed_4h_bars_required")
    last=closed_bars[-(ATR_WINDOW+1):]
    prices=[]
    for i,bar in enumerate(last):
        if i and bar[0]!=last[i-1][0]+STEP:
            raise ValueError("missing_closed_source_4h_bar")
        prices.append(_market_ohlc(bar))
    with localcontext() as ctx:
        ctx.prec=40
        ranges=[]
        for i in range(1,len(prices)):
            _,hi,lo,_,_=prices[i]
            prev=prices[i-1][3]
            ranges.append(max(hi-lo,abs(hi-prev),abs(lo-prev)))
        atr=sum(ranges,D(0))/D(ATR_WINDOW)
        if atr<=0 or not atr.is_finite():
            raise ValueError("zero_or_invalid_ATR_no_protective_quote")
        return atr


def research_entry_geometry(closed_signal_bars,proposed_entry_open_ms,proposed_next_open_price):
    if type(proposed_entry_open_ms) is not int or proposed_entry_open_ms!=closed_signal_bars[-1][0]+STEP:
        raise ValueError("future_or_past_entry_clock_disagrees_with_closed_signal")
    entry=D(str(proposed_next_open_price))
    if not entry.is_finite() or entry<=0:
        raise ValueError("invalid_unexecutable_next_open_price")
    atr=atr14_from_confirmed_signal_history(closed_signal_bars)
    stop=entry-ATR_MULTIPLIER*atr
    if stop<=0:raise ValueError("ATR_stop_nonpositive_not_tradeable")
    return {
        "signal_bar_start_ms":closed_signal_bars[-1][0],
        "next_open_reference_ms":proposed_entry_open_ms,
        "unexecutable_entry_open_quote":str(entry),
        "ATR14_from_prior_closed_4h_bars":str(atr),
        "ATR14_multiplier":"2",
        "initial_prearm_stop_reference_price":str(stop),
        "stop_distance_quote":str(entry-stop),
        "stop_distance_pct_of_assumed_entry":str((entry-stop)/entry*100),
        "no_fill_or_risk_cap_guarantee":True,
        "source_bar_low_after_entry_not_read_by_this_calculation":True
    }


def hypothetical_risk_budget_geometry(geometry,budget_pct,fee,slippage,capital=REFERENCE_CASH):
    """Risk cap applies only to an IDEAL stop fill; gaps may exceed it."""
    b,fee,slippage,capital=map(lambda x:D(str(x)),(budget_pct,fee,slippage,capital))
    if b not in BUDGETS or (fee,slippage) not in COST_PROFILES.values() or capital!=REFERENCE_CASH:
        raise ValueError("budget_or_fee_or_capital_not_in_prelocked_diagnostic_grid")
    entry=D(geometry["unexecutable_entry_open_quote"])
    stop=D(geometry["initial_prearm_stop_reference_price"])
    if not (entry>stop>0):raise ValueError("invalid_ATR_stop_reference")
    per_unit=(entry-stop)+(entry+stop)*(fee+slippage)
    if per_unit<=0:raise ValueError("nonpositive_idealized_risk_unit")
    quote_qty=capital/(entry*(D(1)+fee+slippage))
    ideal_qty=capital*b/D(100)/per_unit
    qty=min(quote_qty,ideal_qty)
    return {
        "diagnostic_only_budget_pct":str(b),
        "capital_reference_usdt":"500",
        "assumed_buy_and_sell_taker_fee_per_side":str(fee),
        "assumed_each_side_slippage_fraction":str(slippage),
        "ATR_initial_stop_reference":str(stop),
        "max_research_qty_btc_if_ideal_stop_fill":str(qty),
        "ideal_stop_risk_notional_usdt":str(qty*per_unit),
        "not_a_real_loss_limit_or_approved_order_size":True
    }


def hypothetical_stop_touch(geometry,held_candle):
    """Reports only possible bar-LOW stop crossing, NOT an exchange fill."""
    _,_,lo,_,_=_market_ohlc(held_candle)
    op=D(str(held_candle[1]))
    stop=D(geometry["initial_prearm_stop_reference_price"])
    if op<=stop:return {"possible_stop_event":"GAP_THROUGH_AT_OPEN",
                        "price_reference_for_hypothetical_exit":str(op),
                        "no_real_fill":True}
    if lo<=stop:return {"possible_stop_event":"LOW_TOUCHED_INTRABAR_UNCERTAIN",
                        "price_reference_for_hypothetical_exit":str(stop),
                        "no_real_fill":True}
    return {"possible_stop_event":"NO_STOP_LOW_CROSS",
            "price_reference_for_hypothetical_exit":None,
            "no_real_fill":True}


def smoke(lock_file,output):
    if output.exists():raise ValueError("refuse_overwrite_prearm_proof")
    pb=lock_file.read_bytes()
    verify_protocol(json.loads(pb))
    result={
        "schema":"nexus.mr40.prospective_prearm_atr14x2_contract_proof.v1",
        "protocol_sha256":hashlib.sha256(pb).hexdigest(),
        "tested_technical_rules":"ATR14 from last 15 verified closed bars, next-open gap, two nonapproved 500USDT budget diagnostics, no assumed actual fills",
        "economic_backtest_completed":False,
        "new_prospective_trades_analysed":0,
        "no_complete_future_archive_consumed":True,
        "prearm_candidate_selected_for_Paper":False,
        "only_public_Bybit_Spot_data_permitted":True,
        "orders":0,"private_api":False,"paper_changed":False,"live":False,"merge":False,"promote":False
    }
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf8") as dst:
        dst.write(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--protocol",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    smoke(a.protocol,a.output)
