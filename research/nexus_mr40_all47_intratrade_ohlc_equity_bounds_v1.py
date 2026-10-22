"""MR40 frozen 47 Spot LONG trades: candle-extreme equity DD bounds.

No exchange connections, runtime orders, strategy promotion or new tuning.
OHLC does not establish intra-4h order of high/low; report lower and
adversarial high-before-low upper bound, NOT an exact floating equity curve.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

from research.nexus_mr40_independent_closed_signal_v1 import (
    frozen_rows,oracle_ledger,canon,STEP,ROWS_SHA,LEDGER_SHA)
from research.nexus_mr40_frozen_47_spot_fee_audit_v1 import (
    START,RATES,get_pairs,match_frozen_comparator,factor)

PROTOCOL="nexus.mr40.all47_frozen_intraposition_ohlc_drawdown_bounds.v1"
PRIOR_AUDIT_SHA="074b74042e62fab437e2d49ce4d8d71c401e301a1d0ad727ed2704a4b012de3d"


def dd_fraction(peak,now):
    if peak<=0 or now<0:
        raise ValueError("invalid_equity")
    return max(D(0), (peak-now)/peak)


def mtm_liquidation_balance(start_balance,entry_price,price,fee):
    """Fee-adjusted hypothetical quote proceeds if liquidated at arbitrary price."""
    return start_balance*(D(1)-fee)*D(price)/D(entry_price)*(D(1)-fee)


def intrapos_risk(rows,pairs,fee):
    """Lower: earlier-bar highs only. Upper: high first, then low in each 4h."""
    if not pairs:
        raise ValueError("empty_trade_window")
    balance=START
    closed_peak=START
    prior_bar_high_peak=START
    high_before_low_peak=START
    closed_maxdd=D(0)
    guaranteed_lower_dd=D(0)
    upper_dd=D(0)
    records=[]
    exposure_bars_total=0
    for i,pair in enumerate(pairs):
        ent=pair["entry_next_open_index"]
        ex=pair["exit_next_open_index"]
        if not (0<=ent<ex<=len(rows)-1):
            raise ValueError("bad_position_range")
        if rows[ent][0]!=pair["entry_next_open_ms"] or rows[ex][0]!=pair["exit_next_open_ms"]:
            raise ValueError("position_timestamps_changed")
        entry_price=D(pair["entry_next_open_price"])
        if entry_price!=D(str(rows[ent][1])):
            raise ValueError("entry_price_mismatch_market")
        trade_start_balance=balance
        trade_min_low=None
        trade_max_high=None
        trade_min_low_ts=None
        pair_lower=D(0)
        pair_upper=D(0)
        for bar_index in range(ent,ex):
            row=rows[bar_index]
            price_high=D(str(row[2]))
            price_low=D(str(row[3]))
            if (not price_low.is_finite() or not price_high.is_finite()
                or price_low<=0 or price_high<price_low):
                raise ValueError("invalid_market_high_low")
            if row[0]!=rows[ent][0]+(bar_index-ent)*STEP:
                raise ValueError("market_bar_gap_within_position")
            hi_equity=mtm_liquidation_balance(trade_start_balance,entry_price,price_high,fee)
            lo_equity=mtm_liquidation_balance(trade_start_balance,entry_price,price_low,fee)
            # Every earlier bar high is chronologically *before* this low,
            # but this same bar's HIGH might have occurred AFTER the LOW.
            lower_here=dd_fraction(prior_bar_high_peak,lo_equity)
            guaranteed_lower_dd=max(guaranteed_lower_dd,lower_here)
            pair_lower=max(pair_lower,lower_here)
            prior_bar_high_peak=max(prior_bar_high_peak,hi_equity)
            # Adversarial within-bar order HIGH -> LOW creates an upper
            # envelope for possible peak-to-trough drawdown in OHLC bars.
            high_before_low_peak=max(high_before_low_peak,hi_equity)
            upper_here=dd_fraction(high_before_low_peak,lo_equity)
            upper_dd=max(upper_dd,upper_here)
            pair_upper=max(pair_upper,upper_here)
            if trade_min_low is None or price_low<trade_min_low:
                trade_min_low=price_low
                trade_min_low_ts=row[0]
            if trade_max_high is None or price_high>trade_max_high:
                trade_max_high=price_high
        # No use of HIGH or LOW of row[ex]: exited at its OPEN.
        natural_exit_price=D(pair["exit_next_open_price"])
        if natural_exit_price!=D(str(rows[ex][1])):
            raise ValueError("exit_price_mismatch_market")
        balance=trade_start_balance*factor(pair,fee)
        closed_peak=max(closed_peak,balance)
        closed_maxdd=max(closed_maxdd,dd_fraction(closed_peak,balance))
        prior_bar_high_peak=max(prior_bar_high_peak,balance)
        high_before_low_peak=max(high_before_low_peak,balance)
        # Previous 4h highs and closes are necessarily before the exit
        # OPEN; if a gap crosses below last LOW, include this close.
        guaranteed_lower_dd=max(guaranteed_lower_dd,dd_fraction(prior_bar_high_peak,balance))
        upper_dd=max(upper_dd,dd_fraction(high_before_low_peak,balance))
        bars_held=ex-ent
        exposure_bars_total+=bars_held
        records.append({
            "trade_index":i+1,
            "window":pair["window"],
            "entry_signal_index":pair["entry_signal_index"],
            "exit_signal_index":pair["exit_signal_index"],
            "entry_open_utc":datetime.fromtimestamp(rows[ent][0]/1000,timezone.utc).isoformat(),
            "exit_open_utc":datetime.fromtimestamp(rows[ex][0]/1000,timezone.utc).isoformat(),
            "holding_complete_4h_candles":bars_held,
            "holding_hours":bars_held*4,
            "entry_open_price":str(entry_price),
            "exit_open_price":str(natural_exit_price),
            "lowest_held_4h_candle_low":str(trade_min_low),
            "lowest_held_candle_open_utc":datetime.fromtimestamp(trade_min_low_ts/1000,timezone.utc).isoformat(),
            "highest_held_4h_candle_high":str(trade_max_high),
            "MAE_price_only_pct_from_entry_OPEN":str((trade_min_low/entry_price-D(1))*D(100)),
            "MFE_price_only_pct_from_entry_OPEN":str((trade_max_high/entry_price-D(1))*D(100)),
            "start_quote_balance_usdt":str(trade_start_balance),
            "realized_exit_quote_balance_usdt":str(balance),
            "max_within_trade_low_vs_prior_bar_high_peaks_lower_bound_pct":str(pair_lower*D(100)),
            "max_high_before_low_4h_path_upper_bound_pct":str(pair_upper*D(100)),
            "not_verified_intrabar_sequence_or_trade_fill":True,
        })
    return {
        "fee_each_side":str(fee),
        "positions":len(pairs),
        "start_quote_usdt":str(START),
        "compounded_realized_end_usdt":str(balance),
        "closed_trade_only_max_dd_pct":str(closed_maxdd*D(100)),
        "guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct":str(guaranteed_lower_dd*D(100)),
        "adversarial_high_before_low_max_dd_upper_bound_pct":str(upper_dd*D(100)),
        "true_intrabar_maxDD_unknown_within_OHLC_bounds":True,
        "total_held_4h_bars":exposure_bars_total,
        "max_holding_4h_bars":max(r["holding_complete_4h_candles"] for r in records),
        "max_holding_hours":max(r["holding_hours"] for r in records),
        "largest_price_only_MAE_pct":str(min(D(r["MAE_price_only_pct_from_entry_OPEN"]) for r in records)),
        "largest_price_only_MFE_pct":str(max(D(r["MFE_price_only_pct_from_entry_OPEN"]) for r in records)),
        "per_position":records,
    }


def validate_previous_group(previous,group,name,now):
    orig=previous["groups"][group][name]
    # The closed-only baseline is required to be exactly the already
    # reported 47-fee audit (same math, same chronological trade sequence).
    old_balance=D(orig["closed_trade_equity_end_usdt"])
    old_dd=D(orig["max_closed_trade_only_drawdown_pct"])
    if (abs(D(now["compounded_realized_end_usdt"])-old_balance)>D("1e-18")
        or abs(D(now["closed_trade_only_max_dd_pct"])-old_dd)>D("1e-18")
        or now["positions"]!=orig["closed_positions"]):
        raise ValueError("intraposition_vs_prior_realized_fee_model_parity_failed")
    lower=D(now["guaranteed_minimum_drawdown_from_prior_4h_highs_to_lows_pct"])
    upper=D(now["adversarial_high_before_low_max_dd_upper_bound_pct"])
    closed=D(now["closed_trade_only_max_dd_pct"])
    if not (D(0)<=closed<=lower<=upper<=D(100)):
        raise ValueError("incorrect_drawdown_bound_ordering")


def run(protocol,inputs,ledger,prior_fee_report,output):
    if output.exists():
        raise ValueError("refuse_overwrite")
    p=json.loads(protocol.read_bytes())
    if (p.get("schema")!=PROTOCOL
        or p["data"]["frozen_ohlcv_sha256"]!=ROWS_SHA
        or p["data"]["frozen_ledger_sha256"]!=LEDGER_SHA
        or p["data"]["previous_fee_audit_full_sha256"]!=PRIOR_AUDIT_SHA
        or p["data"]["positions"]!=47
        or p["equity"]["start_quote_usdt"]!="500"
        or p["controls"]["no_orders"] is not True
        or p["controls"]["no_promotion"] is not True
        or p["controls"]["live"] is not False
        or p["controls"]["PR_draft_no_merge"] is not True):
        raise ValueError("source_risk_study_protocol_not_frozen")
    prescribed={x["name"]:x["taker_fee_each_side"] for x in p["scenarios"]}
    if prescribed!={name:str(rate) for name,rate in RATES.items()}:
        raise ValueError("fee_scenarios_drift")
    rows=frozen_rows(inputs)
    pairs=get_pairs(rows)
    match_frozen_comparator(pairs,oracle_ledger(ledger))
    previous_bytes=prior_fee_report.read_bytes()
    if hashlib.sha256(previous_bytes).hexdigest()!=PRIOR_AUDIT_SHA:
        raise ValueError("prior_realized_fee_audit_SHA_mismatch")
    previous=json.loads(previous_bytes)
    if previous.get("total_pairs")!=47 or previous.get("all_47_entry_exit_next_open_parity") is not True:
        raise ValueError("prior_fee_comparator_incomplete")
    if previous.get("verified_pairs")!=[{**x,"no_real_order_or_fill":True} for x in pairs]:
        raise ValueError("current_positions_do_not_equal_earlier_fee_research")
    splits={
        "train_2023_2024":[x for x in pairs if x["window"]=="train"],
        "evaluation_2025_2026oct19":[x for x in pairs if x["window"]=="evaluation"],
        "combined_chronological_2023_2026oct19":pairs,
    }
    result={}
    for window,subset in splits.items():
        result[window]={}
        for name,fee in RATES.items():
            analysis=intrapos_risk(rows,subset,fee)
            validate_previous_group(previous,window,name,analysis)
            result[window][name]=analysis
    report={
        "schema":"nexus.mr40.frozen47.intraposition_OHLC_equity_bounds.results.v1",
        "protocol_sha256":hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "market_source_sha256":ROWS_SHA,"posthoc_ledger_sha256":LEDGER_SHA,
        "prior_fee_research_sha256":PRIOR_AUDIT_SHA,
        "all_pairs_crosschecked_against_original_47_fee_study":True,
        "source_splits":{"train":25,"evaluation":22,"total":47},
        "groups":result,
        "analysis_not_unseen_OOS":True,
        "max_drawdown_not_exact_because_4h_high_low_order_unknown":True,
        "next_4h_open_not_a_proven_fill":True,
        "account_private_fee_not_known":True,
        "paper_modified":False,"orders":0,"private_API":False,"live":False,
        "merge":False,"promote":False,
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,sort_keys=True,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    brief={
        "digest":report["digest"],"split_sizes":report["source_splits"],
        "risk":{group:{key:{k:v for k,v in info.items() if k!="per_position"}
                       for key,info in scenarios.items()}
                for group,scenarios in result.items()},
    }
    print(json.dumps(brief,ensure_ascii=False))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    for name in ("protocol","inputs","ledger","prior_fee_report","output"):
        parser.add_argument("--"+name,required=True,type=Path)
    args=parser.parse_args()
    run(**vars(args))
