"""One-shot *already-seen* MR40 ATR14x2 pre-arm stop economic smoke test.

Fixed diagnostic, not an optimization, not OOS or a fill simulation grounded in
quotes. Candlestick LOW crossing is only a hypothetical execution proxy.
No orders, no Bybit private API, no Paper application, no runtime imports.
"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
from decimal import Decimal as D,localcontext
from research.nexus_mr40_independent_closed_signal_v1 import frozen_rows,oracle_ledger,canon,ROWS_SHA,LEDGER_SHA
from research.nexus_mr40_frozen_47_spot_fee_audit_v1 import get_pairs,match_frozen_comparator
from research.nexus_mr40_prearm_atr14x2_prospective_v1 import (
    verify_protocol,atr14_from_confirmed_signal_history,research_entry_geometry,
    hypothetical_stop_touch)

LOCK_SCHEMA="nexus.mr40.fixed_prearm_atr14x2_seen_sample_diagnostic_protocol.v1"
EXPECTED_FORWARD_LOCK_SHA="e26ae98b1e2a32aed6ddfdf4abb9aef303a3ff71ac1e9766e3a99f620caf282b"
COSTS=(("fee_only",D("0.001"),D("0")),("stress",D("0.001"),D("0.001")))
START=D("500")
TOTAL_PAIRS=47

def validate_lock(old_lock,forward_bytes):
    p=old_lock
    s=p["scope"]
    if (p.get("schema")!=LOCK_SCHEMA or
        p["preregistered_parent_future_protocol_sha256"]!=EXPECTED_FORWARD_LOCK_SHA or
        hashlib.sha256(forward_bytes).hexdigest()!=EXPECTED_FORWARD_LOCK_SHA or
        p["immutable_seen_8514_market_digest"]!=ROWS_SHA or
        p["immutable_47_position_ledger_file_sha256"]!=LEDGER_SHA or
        s["pairs"]!=47 or s["train"]!=25 or s["evaluation"]!=22 or
        s["candidate"]!="PREARM_ATR14_X2_CLOSED_SIGNAL" or
        s["baseline"]!="UNCHANGED_MR40_BASELINE_NATURAL_EXIT" or
        s["no_other_candidates"] is not True or
        s["same_500USDT_start_each_train_and_evaluation"] is not True or
        s["full_balance_for_both_arms_to_isolate_stop_effect"] is not True or
        p["stop"]["multiplier"]!="2" or
        p["fee_slip_cases"]!={"fee_only":{"side_fee":"0.001","side_slippage":"0"},
                               "stress":{"side_fee":"0.001","side_slippage":"0.001"}} or
        any(p["safety"][k] for k in ("orders","private_api","paper_modified","live","merge","promote"))
    ):
        # no_scheduler must be true, checked separately
        if p["safety"].get("no_scheduler") is not True:
            raise ValueError("old_sample_ATR_study_scheduler_not_allowed")
        raise ValueError("old_sample_ATR_study_lock_drift")
    if p["safety"]["no_scheduler"] is not True:
        raise ValueError("old_sample_ATR_study_scheduler_not_allowed")


def _close_equity(qty,mark,fee,cash_free=D(0)):
    return cash_free+qty*mark*(D(1)-fee)


def one_portfolio(rows,pairs,fee,slip,protected):
    if not pairs:raise ValueError("empty_immutable_pair_split")
    balance=START;peak=START;max_dd=D(0)
    worst=None;events=[]
    for i,pair in enumerate(pairs):
        ent,ex=pair["entry_next_open_index"],pair["exit_next_open_index"]
        if not 0<ent<ex<len(rows):raise ValueError("corrupt_existing_episode_indices")
        open_px=D(pair["entry_next_open_price"]);natural_exit=D(pair["exit_next_open_price"])
        qty=balance*(D(1)-fee)/(open_px*(D(1)+slip))
        if qty<=0 or not qty.is_finite():raise ValueError("invalid_modeled_buy_size")
        stop_geometry=None;stop=D(0)
        if protected:
            # Only completed signal bar and its PRECEDING candles are allowed.
            # The held entry OPEN candle's HIGH/LOW/CLOSE cannot be read here.
            stop_geometry=research_entry_geometry(
                rows[:ent],rows[ent][0],open_px)
            stop=D(stop_geometry["initial_prearm_stop_reference_price"])
        event="NATURAL_NEXT_OPEN";exit_ref=natural_exit;exit_bar_start=None
        bars_observed=0
        for k in range(ent,ex):
            bar=rows[k];op,hi,lo=map(lambda v:D(str(v)),(bar[1],bar[2],bar[3]))
            if (min(op,hi,lo)<=0 or hi<op or lo>op or
                (k>ent and bar[0]!=rows[k-1][0]+14400000)):
                raise ValueError("invalid_frozen_held_candle")
            bars_observed+=1
            # Adversarial HIGH-then-LOW order is a modelled conservative
            # mark-to-market excursion, not actual intra-4h trade sequence.
            hi_mark=_close_equity(qty,hi,fee)
            if hi_mark>peak:peak=hi_mark
            status=hypothetical_stop_touch(stop_geometry,bar) if protected else None
            if status and status["possible_stop_event"]!="NO_STOP_LOW_CROSS":
                event=status["possible_stop_event"]
                exit_ref=D(status["price_reference_for_hypothetical_exit"])
                exit_bar_start=bar[0]
                low_mark=_close_equity(qty,exit_ref,fee)
            else:
                low_mark=_close_equity(qty,lo,fee)
            dd=(peak-low_mark)/peak
            if dd>max_dd:
                max_dd=dd
                worst={"trade_index_in_group":i+1,"entry_signal_index":pair["entry_signal_index"],
                       "held_bar_start_ms":bar[0],"worst_observed_price_reference":str(exit_ref if event!="NATURAL_NEXT_OPEN" else lo),
                       "modeled_intraposition_drawdown_pct":str(dd*D(100))}
            if event!="NATURAL_NEXT_OPEN":
                break
        balance=qty*exit_ref*(D(1)-slip)*(D(1)-fee)
        peak=max(peak,balance)
        if (peak-balance)/peak>max_dd:
            max_dd=(peak-balance)/peak
        if not balance.is_finite() or balance<=0:raise ValueError("invalid_simulated_cash")
        events.append({"index_in_group":i+1,"trade_entry_ms":pair["entry_next_open_ms"],
                       "original_exit_ms":pair["exit_next_open_ms"],
                       "closed_position_reason":event,
                       "hypothetical_stop_quote":str(stop) if protected else None,
                       "hold_bars_until_proxy_exit":bars_observed,
                       "natural_next_open_ref_not_an_actual_fill":True,
                       "stop_intrabar_touch_price_is_not_an_actual_fill":True})
    return {"start_cash_usdt":str(START),"modeled_end_cash_usdt":str(balance),
            "modeled_net_PNL_usdt":str(balance-START),
            "modeled_max_intraposition_high_then_low_drawdown_pct":str(max_dd*D(100)),
            "historical_completed_pairs":len(pairs),
            "hypothetical_stop_low_touch_count":sum(x["closed_position_reason"]!="NATURAL_NEXT_OPEN" for x in events),
            "gap_below_protective_stop_count":sum(x["closed_position_reason"]=="GAP_THROUGH_AT_OPEN" for x in events),
            "total_observed_held_4h_bars":sum(x["hold_bars_until_proxy_exit"] for x in events),
            "worst_event":worst,
            "episodes":events,
            "historical_retrospective_NOT_new_OOS":True,
            "assumed_stop_fill_not_proven":True}


def run(lock,forward_lock,inputs,ledger,output):
    if output.exists():raise ValueError("refuse_overwrite_old_sample_smoke")
    a=lock.read_bytes();b=forward_lock.read_bytes()
    verify_protocol(json.loads(b))
    validate_lock(json.loads(a),b)
    rows=frozen_rows(inputs);pairs=get_pairs(rows)
    match_frozen_comparator(pairs,oracle_ledger(ledger))
    if len(rows)!=8514 or len(pairs)!=47:
        raise ValueError("frozen_history_drift")
    slices={"train_25":[v for v in pairs if v["window"]=="train"],
            "evaluation_22":[v for v in pairs if v["window"]=="evaluation"],
            "all47_chronological":pairs}
    if len(slices["train_25"])!=25 or len(slices["evaluation_22"])!=22:
        raise ValueError("frozen_split_drift")
    comparison={}
    for group,cases in slices.items():
        comparison[group]={}
        for label,fee,slip in COSTS:
            base=one_portfolio(rows,cases,fee,slip,False)
            atr=one_portfolio(rows,cases,fee,slip,True)
            comparison[group][label]={
                "baseline":base,"candidate_atr14x2":atr,
                "candidate_terminal_cash_minus_baseline_usdt":str(D(atr["modeled_end_cash_usdt"])-D(base["modeled_end_cash_usdt"])),
                "candidate_worst_intraposition_DD_minus_baseline_percentage_points":str(D(atr["modeled_max_intraposition_high_then_low_drawdown_pct"])-D(base["modeled_max_intraposition_high_then_low_drawdown_pct"]))
            }
    # In fee-only historical old baseline the same exact fee convention is
    # independently documented in the immutable 47-pair full compounding study.
    expected=D("822.7437089338675974755875079")
    got=D(comparison["all47_chronological"]["fee_only"]["baseline"]["modeled_end_cash_usdt"])
    if abs(got-expected)>D("1e-15"):
        raise ValueError("FAIL_INDEPENDENT_PRIOR_47_FEE_ONLY_ACCOUNT_PARITY")
    report={
        "schema":"nexus.mr40.fixed_atr14x2_old47_fee_and_intrapos_DD_sanity_v1",
        "protocol_sha256":hashlib.sha256(a).hexdigest(),
        "parent_prospective_protocol_sha256":hashlib.sha256(b).hexdigest(),
        "original_market_digest":ROWS_SHA,"original_ledger_sha256":LEDGER_SHA,
        "47_original_pair_parity":True,
        "fix_one_prearm_ATR14x2_stop_before_historical_results":True,
        "compared_cases":["baseline","PREARM_ATR14_X2_CLOSED_SIGNAL"],
        "past_sample_was_already_seen":True,
        "not_new_OOS":True,
        "executions_are_unexecutable_4h_open_or_low_stop_proxies":True,
        "intrabar_equity_path_assumes_high_before_low_not_proven":True,
        "no_order_book_or_latency_or_reliable_actual_stop_fill":True,
        "results":comparison,
        "no_parameter_change_based_on_this_output":True,
        "paper_modified":False,"private_API":False,"orders":0,
        "live":False,"merge":False,"promote":False
    }
    report["digest"]=hashlib.sha256(canon(report)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open("x",encoding="utf8") as f:
        f.write(json.dumps(report,sort_keys=True,indent=2,ensure_ascii=False)+"\n")
    slim={}
    for group,scenarios in comparison.items():
        slim[group]={}
        for label,s in scenarios.items():
            slim[group][label]={
                "base_end":s["baseline"]["modeled_end_cash_usdt"],
                "atr_end":s["candidate_atr14x2"]["modeled_end_cash_usdt"],
                "base_model_dd_pct":s["baseline"]["modeled_max_intraposition_high_then_low_drawdown_pct"],
                "atr_model_dd_pct":s["candidate_atr14x2"]["modeled_max_intraposition_high_then_low_drawdown_pct"],
                "atr_stop_events":s["candidate_atr14x2"]["hypothetical_stop_low_touch_count"],
                "atr_gap_events":s["candidate_atr14x2"]["gap_below_protective_stop_count"]
            }
    print(json.dumps({"digest":report["digest"],"diagnostic_metrics":slim},ensure_ascii=False))

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for name in ("lock","forward_lock","inputs","ledger","output"):
        p.add_argument("--"+name,type=Path,required=True)
    run(**vars(p.parse_args()))
