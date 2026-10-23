"""SHA-pinned posthoc join of pre-profit-arm MR40 losers and 4h adverse clocks.

This is NOT stop backtesting, exit simulation, risk-budget selection or a
transaction. Bybit 4h OHLC lows have unknown intrabar arrival and fill quality.
Old staged-stop realized PnL used a distinct 10k quote research model; the
47-trade adverse excursion tracks price only, not a 500-vs-10k PnL delta.
"""
from __future__ import annotations
import argparse,hashlib,json
from decimal import Decimal as D
from pathlib import Path
from research.nexus_mr40_independent_closed_signal_v1 import canon

INPUTS={
 "adverse_timing":("a751184655ab27e6381274cd07a48d3ebea8589a8527c1407d804f04f3ce8da1",
                   "829214c448b82c8c0ac1a29980fb3fb3d03350d0060f5068e7a25cd4fc524806"),
 "prior_ratchet":("423aa9c28fbb3e23ebce62ea1e731db8922a84ee87da04f891473c9a236852bc",
                 "2a8f7d1c97b0eadb4b719ad65ddb8aa6543eb3a972c84921e6dbf3d137f22db1"),
 "overlay_failure_audit":("fc8fe0c2ab55aff7c5ad7ee1cbda3e9cb10486992423d84ffa2bbc1b104a89cdf",
                          "6c83165729d10b07a166ca6eb4ce8694291f7928b32764108c6a36730474c82a"),
}

def verify_file(path,key):
    raw=path.read_bytes()
    expected,digest=INPUTS[key]
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError("SOURCE_SHA_DRIFT_"+key)
    obj=json.loads(raw)
    claimed=obj.pop("digest",None)
    if claimed!=digest or hashlib.sha256(canon(obj)).hexdigest()!=digest:
        raise ValueError("SOURCE_CANONICAL_DIGEST_DRIFT_"+key)
    return obj

def join(adverse,ratchet,prior):
    events=adverse["per_position"]
    if len(events)!=47 or adverse["group_stats"]["all_47"]["positions"]!=47:
        raise ValueError("SOURCE_47_EPISODES_CHANGED")
    # Bybit old Stop audit and 47 episode timing use different quote accounting
    # but must describe the SAME episode before loss-clocks can be joined.
    if prior["ratchet_failure_mode"]["evaluation_baseline_loss_makers"]!=4 or not prior["ratchet_failure_mode"]["no_2pct_completed_close_arm_on_any_eval_loser"]:
        raise ValueError("PRIOR_RATCHET_FAILURE_CAUSE_CHANGED")
    unique={}
    for e in events:
        k=(e["entry_open_utc"],e["exit_open_utc"])
        if k in unique:raise ValueError("DUPLICATE_FROZEN_EPISODE")
        unique[k]=e
    windows={}
    for group in ("train","evaluation"):
        source=ratchet["unarmed_loss_coverage"][group]
        losers=source["losers"]
        unarmed=source["losers_without_2pct_closed_trigger"]
        if not (losers>=unarmed==len(source["worst_unarmed"])==4):
            raise ValueError("OLD_UNARMED_COUNT_CHANGED_"+group)
        if group=="evaluation" and losers!=4:
            raise ValueError("ALL_FOUR_EVAL_LOSERS_EXPECTED")
        results=[]
        for old in source["worst_unarmed"]:
            key=(old["entry_utc"],old["exit_utc"])
            if key not in unique:raise ValueError("UNARMED_EVENT_UNMATCHED_"+group)
            e=unique[key]
            if e["window"]!=group or old["hit_arm2_close"] is not False or old["first_arm_close_utc"] is not None or D(str(old["max_completed_close_gain_pct"]))>=D("2"):
                raise ValueError("UNARMED_EVENT_MARKET_CLOCK_OR_GAIN_CONTRADICTION")
            mae=D(e["whole_position_adverse_price_MAE_pct"])
            if not mae.is_finite() or mae<0:raise ValueError("INVALID_PRICE_MAE")
            event={}
            for threshold in ("5","10","15"):
                first=e["first_threshold_breach"][threshold]
                if (first is None)!=(mae<D(threshold)):
                    raise ValueError("LOW_THRESHOLD_VS_FULL_MAE_INCONSISTENT")
                event[threshold]=None if first is None else {
                    "candle_open_utc":first["bar_start_utc"],
                    "candle_close_utc":first["bar_end_utc"],
                    "hours_from_entry_to_candle_open":first["hour_age_at_bar_start"],
                    "clock_band":first["band"],
                    "exact_low_touch_and_real_stop_fill_unknown":True,
                }
            results.append({
                "previous_47_position_index":e["trade_index"],
                "entry_open_utc":old["entry_utc"],"exit_open_utc":old["exit_utc"],
                "prior_10k_quote_baseline_PnL_not_comparable_to_500_USDT":old["baseline_pnl"],
                "closed_bar_gain_never_armed_2pct":old["max_completed_close_gain_pct"],
                "max_historical_held_price_MAE_pct":str(mae),
                "first_diagnostic_LOW_breach":event,
                "not_an_actual_stop_or_trade_fill":True
            })
        results.sort(key=lambda x:x["entry_open_utc"])
        windows[group]={
            "all_prior_baseline_losers":losers,
            "unarmed_prior_baseline_losers":unarmed,
            "unarmed_loser_count_with_candle_low_5pct":sum(r["first_diagnostic_LOW_breach"]["5"] is not None for r in results),
            "unarmed_loser_count_with_candle_low_10pct":sum(r["first_diagnostic_LOW_breach"]["10"] is not None for r in results),
            "unarmed_loser_count_with_candle_low_15pct":sum(r["first_diagnostic_LOW_breach"]["15"] is not None for r in results),
            "unarmed_loser_count_never_reaching_5pct_low":sum(r["first_diagnostic_LOW_breach"]["5"] is None for r in results),
            "unarmed_loser_episode_source_matches":len(results),
            "episodes":results
        }
    if windows["evaluation"]["unarmed_loser_count_with_candle_low_5pct"]!=2 or windows["evaluation"]["unarmed_loser_count_with_candle_low_10pct"]!=1:
        raise ValueError("EVAL_PREARM_RISK_PROFILE_CHANGED")
    if windows["train"]["unarmed_loser_count_with_candle_low_5pct"]!=2:
        raise ValueError("TRAIN_PREARM_RISK_PROFILE_CHANGED")
    return {
        "schema":"nexus.mr40.pre_profit_arm_unprotected_loser_4h_low_source_join_v1",
        "classification":"ALREADY_OBSERVED_HISTORICAL_PRICE_RISK_DIAGNOSTIC_NO_NEW_BACKTEST",
        "prior_source_SHA256":{k:v[0] for k,v in INPUTS.items()},
        "train_and_evaluation_are_not_unseen_OOS":True,
        "equity_models_not_interchangeable":True,
        "research_only":True,
        "windows":windows,
        "decision":{
            "profit_trigger_only_stop_protects_unarmed_4h_losers":False,
            "5pct_price_LOW_breach_is_NOT_an_executable_5pct_stop":True,
            "do_not_select_new_stop_level_from_this_sample":True,
            "paper_or_live_promotion_authorized":False,
            "next_valid_research":"Preserve exact historical risk episode identities; prospectively test pre-arm risk limits, with explicit user risk budget and public source continuity before applying to Paper."
        },
        "orders":0,"private_API":False,"Paper_500USDT_changed":False,
        "Live":False,"merge":False,"promote":False
    }

def run(adverse_timing,prior_ratchet,overlay_failure_audit,output):
    if output.exists():raise ValueError("REFUSE_OVERWRITE_EXISTING_PRIOR_AUDIT")
    source={
        "adverse_timing":verify_file(adverse_timing,"adverse_timing"),
        "prior_ratchet":verify_file(prior_ratchet,"prior_ratchet"),
        "overlay_failure_audit":verify_file(overlay_failure_audit,"overlay_failure_audit"),
    }
    result=join(source["adverse_timing"],source["prior_ratchet"],source["overlay_failure_audit"])
    result["digest"]=hashlib.sha256(canon(result)).hexdigest()
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,sort_keys=True,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"digest":result["digest"],"windows":{k:{m:v for m,v in o.items() if m!="episodes"}
                       for k,o in result["windows"].items()}},ensure_ascii=False))

if __name__=="__main__":
    a=argparse.ArgumentParser()
    for key in (*INPUTS,"output"):a.add_argument("--"+key,type=Path,required=True)
    run(**vars(a.parse_args()))
