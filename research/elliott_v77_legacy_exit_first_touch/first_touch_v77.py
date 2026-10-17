"""V77: verify FIRST stop/target touch across every archived 15m exposure bar.

The frozen V71 matched only final exit bars to Bybit archives. This adds an
independent check that earlier bars did not already cross a bound. Costs,
positions and original exits never change. No real fills or trade authority.
"""
from __future__ import annotations
import argparse,json
from collections import Counter,defaultdict
from hashlib import sha256
from pathlib import Path
import pandas as pd
from audit_legacy_entries_v71 import (
  audit as audit_v71,require_digest,EXPECTED_TRACE_SHA,EXPECTED_RESULTS_SHA,
  EXPECTED_V37_SHA,expected_exit_from_completed_bar,verify_bar_timestamps,utc,
)
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
NEW_PNL=None

def digest(f):
    h=sha256()
    with Path(f).open("rb") as source:
        for chunk in iter(lambda:source.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def first_touch_path(frame,trade):
    """Price excursions are reference OHLC, not signed executable fills."""
    fi=int(trade["fill"]["bar_index"])
    ei=int(trade["exit"]["bar_index"])
    if not (0<=fi<=ei<len(frame) and int(trade["exposure_bars"])==ei-fi+1):
        raise ValueError("INVALID_TRADE_EXPOSURE_INDICES")
    entry=float(trade["entry_reference"])
    stop=float(trade["stop"])
    target=float(trade["target"])
    risk=entry-stop
    if not (0<stop<entry<target):raise ValueError("INVALID_FROZEN_STOP_TARGET_ORIENTATION")
    first_stop=None;first_target=None;first_dual=None
    hi=-float("inf");lo=float("inf")
    max_preexit_high=-float("inf");min_preexit_low=float("inf")
    for offset,i in enumerate(range(fi,ei+1)):
        o,h,l,c=(float(frame[field].iloc[i]) for field in ("open","high","low","close"))
        if not (0<l<=min(o,c)<=max(o,c)<=h):
            raise ValueError("INVALID_PHYSICAL_BAR_OHLC")
        hi=max(hi,h);lo=min(lo,l)
        if i<ei:
            max_preexit_high=max(max_preexit_high,h)
            min_preexit_low=min(min_preexit_low,l)
        both=l<=stop and h>=target
        if l<=stop and first_stop is None:first_stop=i
        if h>=target and first_target is None:first_target=i
        if both and first_dual is None:first_dual=i
        if i<ei and (l<=stop or h>=target):
            raise ValueError("PRIOR_STOP_OR_TARGET_TOUCHED_BUT_SIMULATOR_HELD")
        if i<ei and offset+1>=64:
            raise ValueError("TIME_EXIT_DELAYED_BEYOND_64_BARS")
    x={field:float(frame[field].iloc[ei]) for field in ("open","high","low","close")}
    px,kind,dual=expected_exit_from_completed_bar(
        x["open"],x["high"],x["low"],x["close"],stop,target,ei-fi+1)
    if kind!=trade["exit_reason"] or abs(px-float(trade["exit_reference"]))>1e-6:
        raise ValueError("TERMINAL_PRICE_OR_EXIT_REASON_DIFFERENT")
    if kind in ("stop","stop_open_gap") and first_stop!=ei:
        raise ValueError("STOP_OCCURRED_OUTSIDE_TERMINAL_BAR")
    if kind=="target" and first_target!=ei:
        raise ValueError("TARGET_OCCURRED_OUTSIDE_TERMINAL_BAR")
    return dict(
        entry_bar=fi,exit_bar=ei,exposure_bars=ei-fi+1,
        exit_reason=kind,
        first_stop_touch_bar=first_stop,
        first_target_touch_bar=first_target,
        both_touched_terminal=dual,
        prior_exit_touch_count=0,
        preexit_favorable_R=((max_preexit_high-entry)/risk if ei>fi else None),
        preexit_adverse_R=((entry-min_preexit_low)/risk if ei>fi else None),
        full_hold_favorable_R=(hi-entry)/risk,
        full_hold_adverse_R=(entry-lo)/risk,
        target_reward_to_stop_risk_R=(target-entry)/risk,
        invalid_earlier_exit=False
    )

def audit(source_archive,trace_path,result_path,v37_path):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    for path,expected in (
        (trace_path,EXPECTED_TRACE_SHA),
        (result_path,EXPECTED_RESULTS_SHA),
        (v37_path,EXPECTED_V37_SHA),
    ):require_digest(path,expected)
    # Re-run the full V71 source/time/final-exit provenance before the new
    # first-touch across-all-interior-bars validation.
    prior=audit_v71(source_archive,trace_path,result_path,v37_path)
    if (prior["scenarios_checked"]!=20 or
        not prior["all_entries_verified_next_bar_open"] or
        not prior["all_exit_references_verified_against_archived15m"]):
        raise ValueError("PRIOR_SOURCE_BOUND_V71_PROOF_MISSING")
    trace=json.loads(Path(trace_path).read_text(encoding="utf8"))
    frames={}
    for sym in ("BTCUSDT","ETHUSDT"):
        f=load_verified_archive_frame(source_archive,sym,"minute15")
        t=pd.DatetimeIndex(pd.to_datetime(f["timestamp"],utc=True))
        if (not t.is_unique or not t.is_monotonic_increasing or
            not (t[1:]-t[:-1]==pd.Timedelta(minutes=15)).all()):
            raise ValueError("SOURCE_HAS_UNCLOSED_OR_GAPPED_15M_BARS")
        frames[sym]=(f,t)
    bygroup=defaultdict(Counter)
    seen={}
    outcomes=Counter()
    details=[]
    for row in trace["rows"]:
        sym,part,profile=row["symbol"],row["part"],row["profile"]
        frame,times=frames[sym]
        for trade in row["trades"]:
            key=(sym,part,int(trade["trade_index"]))
            this=first_touch_path(frame,trade)
            fi,ei=this["entry_bar"],this["exit_bar"]
            verify_bar_timestamps(fi,trade["fill"],times[fi])
            verify_bar_timestamps(ei,trade["exit"],times[ei])
            if profile in seen.setdefault(key,{}):
                raise ValueError("DUPLICATE_PROFILE_TRADE")
            seen[key][profile]=(fi,ei,this["exit_reason"])
            bygroup[part][this["exit_reason"]]+=1
            outcomes[this["exit_reason"]]+=1
            details.append(dict(symbol=sym,partition=part,profile=profile,
                trade_index=int(trade["trade_index"]),**this))
    if (len(details)!=20 or len(seen)!=10 or
        any(set(v)!={"stress","conservative"} for v in seen.values())):
        raise ValueError("COST_PROFILE_PAIRING_INCOMPLETE")
    if any(p["stress"][0]!=p["conservative"][0] or
           p["stress"][2]!=p["conservative"][2] for p in seen.values()):
        raise ValueError("COST_PROFILE_ENTRY_OR_EXIT_REASON_DISAGREEMENT")
    altered_exit_times=sum(p["stress"][1]!=p["conservative"][1]
                           for p in seen.values())
    if outcomes["stop"]!=12 or outcomes["target"]!=8 or sum(outcomes.values())!=20:
        raise ValueError("PHYSICAL_EXIT_DISTRIBUTION_CHANGED")
    return dict(
        schema="nexus.elliott-v77-first-touch-source-causal-exit-audit.v1",
        frozen_trace_sha256=digest(trace_path),
        frozen_result_sha256=digest(result_path),
        frozen_v37_sha256=digest(v37_path),
        historical_previously_inspected=True,
        archived_15m_physical_validation_performed=True,
        original_next_bar_entry_and_terminal_exit_v71_rechecked=True,
        different_historical_simulated_trades=len(seen),
        paired_cost_profile_exit_paths_checked=len(details),
        same_original_entries_across_cost_profiles=True,
        cost_profile_changed_exit_bar_count=altered_exit_times,
        cost_profiles_can_change_stop_target_exit_time=True,
        all_preexit_source_bars_checked_for_early_touch=True,
        incorrect_early_exit_holds_detected=0,
        terminal_exit_causes=dict(outcomes),
        partition_exit_counts={key:dict(c) for key,c in bygroup.items()},
        per_trade=details,
        cannot_determine_intrabar_tick_order=True,
        original_strategy_remains_loss_making=True,
        demo_promotion=False,entry_signal=False,paper_eligible=False,
        live_enabled=False,new_pnl=None
    )

def main():
    p=argparse.ArgumentParser()
    for key in ("archive","trace","result","v37","output"):
        p.add_argument("--"+key,required=True)
    args=p.parse_args()
    path=Path(args.output)
    if path.exists():raise RuntimeError("IMMUTABLE_RECEIPT_EXISTS")
    data=audit(args.archive,args.trace,args.result,args.v37)
    path.write_text(json.dumps(data,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({
        "different_trades":data["different_historical_simulated_trades"],
        "paired_profiles":data["paired_cost_profile_exit_paths_checked"],
        "early_touch_errors":data["incorrect_early_exit_holds_detected"],
        "cost_profile_different_exit_bars":data["cost_profile_changed_exit_bar_count"],
        "exit_reasons":data["terminal_exit_causes"],
        "receipt_sha256":digest(path)
    },ensure_ascii=False))
if __name__=="__main__":main()
