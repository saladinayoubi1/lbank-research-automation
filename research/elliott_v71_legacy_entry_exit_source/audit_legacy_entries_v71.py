"""V71 independent archived-15m legacy trade chronology and exit-priority QA.

Physical historical Bybit 15m frames are reopened via the original immutable
verified-archive loader, then every recorded legacy Elliott simulation trade
is matched to source bar times/opens/highs/lows/closes. It does not prove
intrabar tick execution or candidate-feature non-leakage and cannot trade.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
from decimal import Decimal
import hashlib,json
from pathlib import Path
import pandas as pd
# Verified legacy archive loader is imported only by physical audit mode.
# Pure morphology/chronology regression tests require no private archive.

EXPECTED_TRACE_SHA="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
EXPECTED_RESULTS_SHA="02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc"
EXPECTED_V37_SHA="96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024"
BARS=pd.Timedelta(minutes=15)
RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
AUTO_DEMO=False
ENTRY_SIGNAL=False
FILLED_ORDERS_CONFIRMED=False

def digest(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()
def require_digest(path,expected):
    if digest(path)!=expected:raise ValueError("FROZEN_PHYSICAL_SOURCE_HASH_CHANGED")
def within(x,y,tol=1e-6):
    return abs(float(x)-float(y))<=tol
def utc(x):
    s=pd.Timestamp(x)
    if s.tzinfo is None or s.utcoffset() is None:raise ValueError("NAIVE_SOURCE_OR_TRACE_TIMESTAMP")
    return s.tz_convert("UTC")
def expected_exit_from_completed_bar(open_,high,low,close,stop,target,age):
    """Same conservative stop-first OHLC convention; no intrabar tick claim."""
    o,h,l,c,s,g=map(float,(open_,high,low,close,stop,target))
    if not (0<l<=min(o,c)<=max(o,c)<=h and 0<s<g):
        raise ValueError("INVALID_EXIT_BAR_OR_LEVELS")
    dual=l<=s and h>=g
    if l<=s:
        return min(o,s),"stop_open_gap" if o<s else "stop",dual
    if h>=g:return g,"target",dual
    if int(age)>=64:return c,"time_64_bars",dual
    return c,"terminal_liquidation",dual

def verify_bar_timestamps(index,evidence,source_open):
    """The recorded bar stamp must equal actual 15m open/closed UTC."""
    actual=utc(source_open)
    if (type(index) is not int or index<0 or
        utc(evidence["open_at"])!=actual or
        utc(evidence["decision_at"])!=actual+BARS):
        raise ValueError("SOURCE_BAR_CLOCK_OR_TRACE_DOES_NOT_MATCH")

def audit(archive,trace_path,result_path,v37_path):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    for p,h in ((trace_path,EXPECTED_TRACE_SHA),(result_path,EXPECTED_RESULTS_SHA),
                (v37_path,EXPECTED_V37_SHA)):require_digest(p,h)
    trace=json.loads(Path(trace_path).read_text(encoding="utf8"))
    result=json.loads(Path(result_path).read_text(encoding="utf8"))
    v37=json.loads(Path(v37_path).read_text(encoding="utf8"))
    if (trace.get("live_enabled") is not False or
        result.get("research_only") is not True or
        result.get("auto_demo_promotion") is not False or
        result.get("live_enabled") is not False or
        len(result["rows"])!=12 or len(trace["rows"])!=12):
        raise ValueError("UNTRUSTED_RESEARCH_TRACE")
    frames={}
    summary=Counter();seen={};pairs={}
    source_hashes={}
    validations=[]
    for symbol in ("BTCUSDT","ETHUSDT"):
        frame=load_verified_archive_frame(archive,symbol,"minute15")
        if not {"timestamp","open","high","low","close"}.issubset(frame):raise ValueError("MISSING_VERIFIED_15M_FIELDS")
        t=pd.DatetimeIndex(pd.to_datetime(frame["timestamp"],utc=True))
        if not t.is_unique or not t.is_monotonic_increasing or any(t[1:]-t[:-1]!=BARS):
            raise ValueError("ARCHIVE_15M_GAPS_OR_DUPLICATES")
        frames[symbol]=(frame,t)
        source_hashes[symbol]=dict(bars=len(frame),first=t[0].isoformat(),last=t[-1].isoformat())
    cells={(a["symbol"],a["part"],a["profile"]):a for a in result["rows"]}
    for block in trace["rows"]:
        sym,part,prof=block["symbol"],block["part"],block["profile"]
        frame,t=frames[sym]
        if (sym,part,prof) not in cells:raise ValueError("MISSING_RESULTS_CELL")
        if len(block["trades"])!=cells[sym,part,prof]["closed_round_trips"]:
            raise ValueError("TRADE_COUNT_DISAGREEMENT")
        for trade in block["trades"]:
            entry=trade["fill"];decision=trade["decision"];exit_=trade["exit"]
            di,fi,ei=(int(x["bar_index"]) for x in (decision,entry,exit_))
            if not (0<=di<fi<=ei<len(frame) and fi==di+1):
                raise ValueError("NOT_NEXT_OPEN_OR_BACKDATED_EXECUTION")
            for idx,pivot in ((di,decision),(fi,entry),(ei,exit_)):
                verify_bar_timestamps(idx,pivot,t[idx])
            if utc(decision["decision_at"])!=utc(entry["open_at"]):
                raise ValueError("DECISION_LATER_THAN_NEXT_FILL_OPEN")
            for name,source_field in (("entry_reference","open"),):
                if not within(trade[name],frame[source_field].iloc[fi]):
                    raise ValueError("ENTRY_REFERENCE_NOT_VERIFIED_NEXT_OPEN")
            s=float(trade["stop"]);goal=float(trade["target"]);entry_slipped=float(trade["entry_slipped"])
            if not (0<s<entry_slipped<goal):
                raise ValueError("STOP_OR_TARGET_ORIENTATION_INVALID")
            o,h,l,c=tuple(float(frame[k].iloc[ei]) for k in ("open","high","low","close"))
            if not l<=min(o,c)<=max(o,c)<=h:raise ValueError("INVALID_ARCHIVE_EXIT_OHLC")
            expected,kind,dual=expected_exit_from_completed_bar(
                o,h,l,c,s,goal,trade["exposure_bars"])
            if not within(expected,trade["exit_reference"]) or kind!=trade["exit_reason"]:
                raise ValueError("EXIT_PRICE_OR_STOP_FIRST_REASON_WRONG")
            if int(trade["exposure_bars"])!=ei-fi+1:
                raise ValueError("INVALID_EXPOSURE_BARS")
            if float(trade["entry_slipped"])<=0 or float(trade["exit_slipped"])<=0:
                raise ValueError("INVALID_SLIPPED_REFERENCE")
            key=(sym,part,int(trade["trade_index"]))
            if prof in pairs.setdefault(key,{}):raise ValueError("DUPLICATE_SCENARIO_TRADE")
            pairs[key][prof]=(di,fi,ei)
            if dual:summary["both_stop_and_target_touched"]+=1
            summary[kind]+=1;summary["scenario_trades"]+=1
            validations.append(dict(symbol=sym,partition=part,profile=prof,
                decision=decision["decision_at"],fill=entry["open_at"],
                exit=exit_["decision_at"],exit_reason=kind,
                dual_touch=dual))
    if (len(pairs)!=10 or summary["scenario_trades"]!=20 or
        any(set(v)!={"conservative","stress"} for v in pairs.values())):
        raise ValueError("SCENARIO_PAIRING_INCOMPLETE")
    if v37["conservative_total"]["trades"]!=10 or v37["stress_total"]["trades"]!=10:
        raise ValueError("PINNED_REPORT_TRADE_COUNT_MISMATCH")
    return {
        "schema":"nexus.elliott-v71-legacy-archived15m-entry-exit-audit.v1",
        "audited_utc":datetime.now(timezone.utc).isoformat(),
        "source_trace_sha256":EXPECTED_TRACE_SHA,
        "source_result_sha256":EXPECTED_RESULTS_SHA,
        "frozen_v37_sha256":EXPECTED_V37_SHA,
        "verified_archive_15m":source_hashes,
        "scenarios_checked":summary["scenario_trades"],
        "distinct_simulated_trades":len(pairs),
        "stop_priority_dual_touch_count_across_profiles":summary["both_stop_and_target_touched"],
        "exit_reason_counts":dict(summary),
        "all_entries_verified_next_bar_open":True,
        "all_exit_references_verified_against_archived15m":True,
        "independent_feature_leakage_audit_complete":False,
        "tick_orderbook_execution_verified":False,
        "historically_inspected":True,
        "paper_eligible":False,"live_enabled":False,"entry_signal":False,
        "new_pnl":None,"no_promotion":True,
        "scenario_trade_checks":validations,
    }
def main():
    p=argparse.ArgumentParser()
    for k in ("archive","trace","result","v37","output"):
        p.add_argument("--"+k,required=True)
    a=p.parse_args();out=Path(a.output)
    if out.exists():raise RuntimeError("IMMUTABLE_EVIDENCE_EXISTS")
    obj=audit(a.archive,a.trace,a.result,a.v37)
    out.write_text(json.dumps(obj,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({k:obj[k] for k in (
        "scenarios_checked","distinct_simulated_trades",
        "stop_priority_dual_touch_count_across_profiles",
        "all_entries_verified_next_bar_open",
        "all_exit_references_verified_against_archived15m")}))
    print("RECEIPT_SHA256="+digest(out))
if __name__=="__main__":main()
