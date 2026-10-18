"""NEXUS V119 fixed causal W2-support retest: research ONLY, no trading API.

One entirely precommitted Wave0/1/2-like *partial* structural mechanism,
DIFFERENT from V118's Wave1 breakout. Two Bybit public Spot historical
15-minute archives with pinned immutable sha256, inspected historical scope.
No labels asserting full Elliott degree, no hyperparameter selection, Demo
promotion or Live. Next-bar OPEN, realistic adverse side-cost and shared cash.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

SCHEMA="nexus.v119.wave2-physical-support-retest.research.v1"
SYMBOLS=("BTC","ETH")
SHAS={
    "BTC":"c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226",
    "ETH":"ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1",
}
SOURCE_ROWS=128544
SOURCE_START="2022-12-01T00:00:00+00:00"
SOURCE_END="2026-07-31T23:45:00+00:00"
PIVOT_LEFT=PIVOT_RIGHT=3
MIN_WAVE1_MOVE=0.006
RETRACE_LOW=0.382
RETRACE_HIGH=0.886
MAX_SWING_BARS=128
SUPPORT_NEAR_FRACTION=0.15
RECLAIM_ABOVE_FRACTION=0.04
RETEST_HORIZON=48
W2_STOP_BUFFER=0.002
MIN_REWARD_RISK=1.5
TARGET_R_MULTIPLE=2.0
MAX_HOLD=96
CASH=500.0
MAX_NOTIONAL=250.0
MAX_GAPLESS_RISK=2.5
PROFILES={"conservative":(10.0,5.0),"stress":(25.0,15.0)}
RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ENTRY_SIGNAL=False
AUTOMATIC_DEMO_PROMOTION=False


class V119Error(ValueError):
    pass


def canonical_digest(value:Any)->str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(
        ",",":"),allow_nan=False).encode("utf-8")).hexdigest()


def verified_frame(path:Path,symbol:str)->pd.DataFrame:
    if symbol not in SHAS or path.is_symlink() or not path.is_file():
        raise V119Error("missing pinned physical Bybit source")
    if hashlib.sha256(path.read_bytes()).hexdigest()!=SHAS[symbol]:
        raise V119Error("physical Bybit source SHA256 changed")
    frame=pd.read_parquet(path)
    if (set(frame.columns)!={
        "timestamp","open","high","low","close","volume","symbol","timeframe"}
        or len(frame)!=SOURCE_ROWS
        or not (frame["symbol"]==symbol.lower()+"_usdt").all()
        or not (frame["timeframe"]=="minute15").all()):
        raise V119Error("source identity/timeframe/scope mismatch")
    times=pd.to_datetime(frame["timestamp"],utc=True,errors="raise")
    if (times.iloc[0].isoformat()!=SOURCE_START
        or times.iloc[-1].isoformat()!=SOURCE_END
        or not times.is_monotonic_increasing or times.duplicated().any()
        or not (times.diff().iloc[1:]==pd.Timedelta(minutes=15)).all()):
        raise V119Error("physical 15-minute continuity missing")
    nums=frame[["open","high","low","close","volume"]].to_numpy(dtype=float)
    if (not np.isfinite(nums).all() or (nums[:,:4]<=0).any()
        or (nums[:,4]<0).any()
        or (nums[:,1]<np.maximum.reduce((nums[:,0],nums[:,2],nums[:,3]))).any()
        or (nums[:,2]>np.minimum.reduce((nums[:,0],nums[:,1],nums[:,3]))).any()):
        raise V119Error("invalid OHLC physical source")
    return frame.reset_index(drop=True)


def as_arrays(frames:dict[str,pd.DataFrame])->tuple[dict, pd.Series]:
    if set(frames)!=set(SYMBOLS):
        raise V119Error("exact two Bybit Spot symbols required")
    t=pd.to_datetime(frames["BTC"]["timestamp"],utc=True)
    peer=pd.to_datetime(frames["ETH"]["timestamp"],utc=True)
    if not t.equals(peer):
        raise V119Error("uncorrelated BTC/ETH source grid")
    return ({s:{f:frames[s][f].to_numpy(dtype=float) for f in (
        "open","high","low","close")} for s in SYMBOLS},t)


def confirmed_pivots(hi:np.ndarray,lo:np.ndarray)->list[tuple[int,int,str,float]]:
    """Each event is visible ONLY after three physically later closed bars.

    Preserve every strict confirmed event, including same-kind neighbors;
    never prune/refit prior emitted pivots with future changes.
    """
    if (len(hi)!=len(lo) or len(hi)<2*PIVOT_RIGHT+1
        or not np.isfinite(hi).all() or not np.isfinite(lo).all()
        or (lo>hi).any()):
        raise V119Error("invalid physical pivot grid")
    out=[]
    for center in range(PIVOT_LEFT,len(hi)-PIVOT_RIGHT):
        a=center-PIVOT_LEFT
        b=center+PIVOT_RIGHT+1
        high=hi[center]>max(np.max(hi[a:center]),np.max(hi[center+1:b]))
        low=lo[center]<min(np.min(lo[a:center]),np.min(lo[center+1:b]))
        if high==low:   # Dual OHLC centers are unordered; reject.
            continue
        out.append((center+PIVOT_RIGHT,center,
                   "HIGH" if high else "LOW",
                   float(hi[center] if high else lo[center])))
    return out


def support_retest_signals(data:dict[str,np.ndarray],
                           start:int,end:int,symbol:str)->tuple[list[dict],dict]:
    """Closed W2 + physical support retest + reclaim, THEN next open.

    Scans all original confirmed pivot triples, not favorable curated patterns.
    Counts and reasons are research funnel only; not wave certificates.
    """
    if symbol not in SYMBOLS or not 0<=start<end<=len(data["open"]):
        raise V119Error("invalid source research partition")
    pivots=confirmed_pivots(data["high"],data["low"])
    tally=defaultdict(int)
    candidates=[]
    for i in range(2,len(pivots)):
        w0,w1,w2=pivots[i-2:i+1]
        if w2[0]<start or w2[0]>=end:
            continue
        tally["source_confirmed_triplets"]+=1
        if (w0[2],w1[2],w2[2])!=("LOW","HIGH","LOW"):
            tally["non_LHL_source_triplets"]+=1
            continue
        if w2[1]-w0[1]>MAX_SWING_BARS:
            tally["historically_long_triplet"]+=1
            continue
        p0,p1,p2=w0[3],w1[3],w2[3]
        move=p1-p0
        retrace=(p1-p2)/move if move>0 else float("inf")
        if (move<MIN_WAVE1_MOVE*p0 or p2<=p0
            or not RETRACE_LOW<=retrace<=RETRACE_HIGH):
            tally["structural_geometry_failure"]+=1
            continue
        tally["structural_partial_pass_not_wave_certificate"]+=1
        support=p2
        detected=False
        limit=min(end-2,w2[0]+RETEST_HORIZON)
        for j in range(w2[0]+1,limit+1):
            # If invalidated before the retest, forbid future hindsight revival.
            if data["low"][j]<support:
                tally["physical_wave2_support_failed_before_entry"]+=1
                detected=True
                break
            if (data["low"][j]<=support+SUPPORT_NEAR_FRACTION*move
                and data["close"][j]>=support+RECLAIM_ABOVE_FRACTION*move):
                confirmation=j+1
                if (data["low"][confirmation]<support):
                    tally["physical_wave2_support_failed_before_entry"]+=1
                    detected=True
                    break
                if (data["close"][confirmation]>data["open"][confirmation]
                    and data["close"][confirmation]>data["high"][j]
                    and data["close"][confirmation]<p1):
                    fill_i=confirmation+1
                    if fill_i>=end:
                        tally["entry_right_censored"]+=1
                        detected=True
                        break
                    candidates.append({
                        "symbol":symbol,"pivot_w0_center":w0[1],
                        "pivot_w1_center":w1[1],"pivot_w2_center":w2[1],
                        "w2_known_after_closed_index":w2[0],
                        "retest_completed_index":j,
                        "reclaim_completed_index":confirmation,
                        "entry_index":fill_i,
                        "w0_physical_low":p0,"w1_physical_high":p1,
                        "w2_physical_low":p2,
                    })
                    tally["physical_support_reclaim_signals"]+=1
                    detected=True
                    break
        if not detected:
            tally["no_retest_reclaim_within_48_completed_bars"]+=1
    if sum(v for k,v in tally.items() if k in (
        "non_LHL_source_triplets","historically_long_triplet",
        "structural_geometry_failure",
        "physical_wave2_support_failed_before_entry",
        "entry_right_censored","physical_support_reclaim_signals",
        "no_retest_reclaim_within_48_completed_bars",
    ))!=tally["source_confirmed_triplets"]:
        raise V119Error("all original source triplets not accounted")
    return candidates,dict(sorted(tally.items()))


def replay(data:dict[str,dict[str,np.ndarray]], times:pd.Series,
           signals:list[dict],start:int,end:int,profile:str)->dict:
    """One 500-USDT spot cash account, no short, no overlapped positive cash."""
    if profile not in PROFILES or not 0<=start<end<=len(times):
        raise V119Error("invalid physical accounting partition")
    fee_bps,slip_bps=PROFILES[profile]
    fee,slip=fee_bps/10000.0,slip_bps/10000.0
    cash=CASH
    active_until=start
    declined=defaultdict(int)
    booked=[]
    for sig in sorted(signals,key=lambda x:(x["entry_index"],x["symbol"])):
        sym=sig["symbol"]
        i=sig["entry_index"]
        a=data[sym]
        if not start<=i<end:
            raise V119Error("outside replay partition")
        if not (sig["pivot_w2_center"]+PIVOT_RIGHT==
            sig["w2_known_after_closed_index"]
            <sig["retest_completed_index"]
            <sig["reclaim_completed_index"]==i-1):
            raise V119Error("source future leakage in Wave2 chronology")
        if i<active_until:
            declined["cash_book_already_occupied"]+=1
            continue
        mid=float(a["open"][i])
        support=sig["w2_physical_low"]
        stop=support*(1-W2_STOP_BUFFER)
        if (not stop>sig["w0_physical_low"] or mid<=stop or
            mid>=sig["w1_physical_high"]):
            declined["unfavorable_next_open_or_invalid_original_stop"]+=1
            continue
        target=min(sig["w1_physical_high"],mid+TARGET_R_MULTIPLE*(mid-stop))
        if ((target-mid)/(mid-stop)<MIN_REWARD_RISK):
            declined["insufficient_structural_reward_vs_risk"]+=1
            continue
        entry=mid*(1+slip)
        if entry>=target:
            declined["adverse_friction_makes_target_unreachable"]+=1
            continue
        exit_stop=stop*(1-slip)*(1-fee)
        spend_one=entry*(1+fee)
        risk_one=spend_one-exit_stop
        if risk_one<=0:
            raise V119Error("unphysical risk after fee/slippage")
        qty=math.floor(min(
            MAX_NOTIONAL/entry,
            MAX_GAPLESS_RISK/risk_one,
            cash/spend_one
        )*1e8)/1e8
        if qty<=0:
            declined["insufficient_cash_or_risk_budget"]+=1
            continue
        spend=qty*spend_one
        if spend>cash+1e-7 or qty*entry>MAX_NOTIONAL+1e-7 or qty*risk_one>MAX_GAPLESS_RISK+1e-7:
            raise V119Error("shared cash/nominal risk overallocated")
        cash-=spend
        closure=None
        for bar_i in range(i,end):
            # Timeout at next available physical open, never unknown close.
            if bar_i==i+MAX_HOLD or bar_i==end-1:
                closure=(bar_i,float(a["open"][bar_i]),"TIMEOUT_OR_PARTITION_END_OPEN")
                break
            if a["low"][bar_i]<=stop:
                closure=(bar_i,min(float(a["open"][bar_i]),stop),
                         "STRUCTURE_STOP_GAP" if a["open"][bar_i]<stop else
                         "STOP_FIRST_AMBIGUOUS" if a["high"][bar_i]>=target else
                         "STRUCTURE_STOP_ONLY")
                break
            if a["high"][bar_i]>=target:
                closure=(bar_i,target,"PRECOMMITTED_TARGET")
                break
        if closure is None:
            raise V119Error("candidate escaped fixed source end")
        exit_i,exit_mid,why=closure
        proceeds=qty*exit_mid*(1-slip)*(1-fee)
        net=proceeds-spend
        cash+=proceeds
        active_until=exit_i+1  # no same-bar double independent fill
        booked.append({
            "symbol":sym,"entry_index":i,"exit_index":exit_i,
            "exit_utc":pd.Timestamp(times.iloc[exit_i]).isoformat(),
            "cause":why,"net_pnl_usdt":round(net,8),
            "qty":round(qty,8),"entry_mid":round(mid,8),
            "entry_fill":round(entry,8),"structural_stop":round(stop,8),
            "structural_target":round(target,8),
            "entry_cash_spend_usdt":round(spend,8),
            "exit_cash_proceeds_usdt":round(proceeds,8),
        })
    counts=defaultdict(lambda:{"count":0,"pnl":0.0})
    for row in booked:
        x=counts[row["exit_utc"][:7]]
        x["count"]+=1
        x["pnl"]+=row["net_pnl_usdt"]
    monthly=[{
        "month":m,"round_trips":v["count"],"net_pnl_usdt":round(v["pnl"],8),
        "mean_pnl_usdt":round(v["pnl"]/v["count"],8),
    } for m,v in sorted(counts.items())]
    return {
        "status":"EXPLORATORY_COSTED_HISTORICAL_NO_PROMOTION",
        "initial_shared_cash_usdt":CASH,
        "ending_cash_usdt":round(cash,8),
        "net_pnl_usdt":round(cash-CASH,8),
        "round_trips":len(booked),
        "positive_net_trades":sum(x["net_pnl_usdt"]>0 for x in booked),
        "mean_pnl_usdt":round((cash-CASH)/len(booked),8) if booked else None,
        "denied_after_signal":dict(sorted(declined.items())),
        "monthly":monthly,"trades":booked,
        "paper_eligible":False,"live_enabled":False,
    }


def evaluate(btc:Path,eth:Path)->dict:
    frames={sym:verified_frame(path,sym) for sym,path in (("BTC",btc),("ETH",eth))}
    data,times=as_arrays(frames)
    n=len(times)
    splits={
        "training":(64,int(n*.60)),
        "validation_already_inspected":(int(n*.60),int(n*.80)),
        "historical_test_already_inspected":(int(n*.80),n),
    }
    allresults={}
    for name,(start,end) in splits.items():
        signals=[]
        counts={}
        for sym in SYMBOLS:
            proposals,counts[sym]=support_retest_signals(data[sym],start,end,sym)
            signals+=proposals
        allresults[name]={
            "start_utc":pd.Timestamp(times.iloc[start]).isoformat(),
            "end_utc":pd.Timestamp(times.iloc[end-1]).isoformat(),
            "source_triplet_funnel":counts,
            "source_causal_signals":len(signals),
            "profiles":{k:replay(data,times,signals,start,end,k) for k in PROFILES},
        }
    spec={
        "schema":SCHEMA,"strategy":"causal_wave2_physical_support_retest_reclaim_next_open_v1",
        "source_exchange":"Bybit_public_Spot_archive_no_exchange_order_api",
        "source_shas":SHAS,
        "source_closed_bars_per_asset":SOURCE_ROWS,
        "source_start_utc":SOURCE_START,
        "source_end_utc":SOURCE_END,
        "historical_test_already_inspected":True,
        "independent_future_holdout":False,
        "not_full_elliott_wave_certification":True,
        "original_v106_v117_gates_untouched":True,
        "mechanism_not_v118_wave1_breakout":True,
        "single_predeclared_fixed_parameter_configuration":True,
        "input_frozen_config":{
            "pivot_left":PIVOT_LEFT,"pivot_right":PIVOT_RIGHT,
            "min_wave1_relative_move":MIN_WAVE1_MOVE,
            "wave2_retrace_min":RETRACE_LOW,"wave2_retrace_max":RETRACE_HIGH,
            "max_pattern_span_bars":MAX_SWING_BARS,
            "support_near_leg_fraction":SUPPORT_NEAR_FRACTION,
            "reclaim_leg_fraction":RECLAIM_ABOVE_FRACTION,
            "retest_horizon_bars":RETEST_HORIZON,
            "w2_stop_buffer_fraction":W2_STOP_BUFFER,
            "min_structural_reward_risk":MIN_REWARD_RISK,
            "target_r_multiple":TARGET_R_MULTIPLE,
            "max_hold_bars":MAX_HOLD,
            "initial_shared_cash_usdt":CASH,
            "max_notional_usdt":MAX_NOTIONAL,
            "max_nominal_gapless_risk_usdt":MAX_GAPLESS_RISK,
            "fees_slip_each_side_bps":PROFILES,
        },
        "automatic_demo_promotion":False,
        "paper_eligible":False,"live_enabled":False,"orders":0,
        "results":allresults,
        "status":"EXPLORATORY_SOURCE_BOUND_NO_QUALIFICATION",
    }
    return {**spec,"result_digest":canonical_digest(spec)}


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--btc",type=Path,required=True)
    ap.add_argument("--eth",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True)
    args=ap.parse_args()
    if args.output.resolve() in (args.btc.resolve(),args.eth.resolve()):
        raise V119Error("cannot overwrite immutable source")
    result=evaluate(args.btc,args.eth)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists():
        raise V119Error("output is write-once")
    temp=args.output.with_suffix(".tmp")
    with temp.open("w",encoding="utf-8",newline="\n") as f:
        f.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp,args.output)
    print(json.dumps({
        "status":result["status"],"result_digest":result["result_digest"],
        "summary":{k:{
            "source_causal_signals":v["source_causal_signals"],
            "profiles":{p:{key:r[key] for key in (
                "round_trips","positive_net_trades","net_pnl_usdt",
                "mean_pnl_usdt","ending_cash_usdt")}
                for p,r in v["profiles"].items()},
        } for k,v in result["results"].items()},
        "paper_eligible":False,"live_enabled":False,
    },sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
