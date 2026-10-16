"""V73 physically anchored legacy Elliott H1/H4 closed-bar as-of proof.

Original SHA-pinned legacy Bybit source and frozen 10 distinct simulated
decision times. Verifies the original *unchanged* _closed_asof against an
independent latest-completed-candle oracle, with future append/tampering.
This is NOT a full engine no-lookahead proof, not V52 score, no trading.
"""
from __future__ import annotations
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd

EXPECTED_TRACE="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
PROFILES={"conservative","stress"}
RESEARCH_ONLY=True
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
LIVE_ENABLED=False
NEW_PNL=None

def digest(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda:f.read(1048576),b""):h.update(chunk)
    return h.hexdigest()

def context_features(bars, minutes):
    """Mirror the immutable original H1/H4 formulas, never use future rows."""
    if minutes==60:
        rang=(bars["high"].astype(float)-bars["low"].astype(float))/bars["close"].astype(float)
        return {
            "compression":(rang.rolling(6,min_periods=6).mean()
                           <rang.shift(1).rolling(48,min_periods=48).median()*.8).astype(float),
            "vol_ok":(rang<rang.shift(1).rolling(72,min_periods=72).median()*1.65).astype(float)}
    if minutes==240:
        return {
            "up":((bars["close"].astype(float)>bars["close"].shift(1).rolling(12).median())
                  &(bars["low"].astype(float)>bars["low"].shift(4).rolling(8).min())).astype(float),
            "range":((bars["close"].astype(float)<=bars["high"].shift(1).rolling(12).max())
                     &(bars["close"].astype(float)>=bars["low"].shift(1).rolling(12).min())).astype(float)}
    raise ValueError("UNREGISTERED_PARENT_TIMEFRAME")

def audit_asof_one(source,decision_utc,minutes,original_merge):
    """Independent oracle: most recent parent CLOSE <= 15m decision.

    Check full accessible prefix and future-extended/mutated parent bars with
    the exact original time-asof merge function. No partial parent bar used.
    """
    if minutes not in (60,240):raise ValueError("TIMEFRAME_NOT_REGISTERED")
    decision=pd.Timestamp(decision_utc)
    if decision.tzinfo is None or decision.utcoffset() is None:
        raise ValueError("DECISION_TIMESTAMP_NAIVE")
    decision=decision.tz_convert("UTC")
    src=source.reset_index(drop=True).copy()
    raw=pd.DatetimeIndex(pd.to_datetime(src["timestamp"],utc=True,errors="raise"))
    interval=pd.Timedelta(minutes=minutes)
    if (raw.hasnans or not raw.is_unique or not raw.is_monotonic_increasing or
        not (raw[1:]-raw[:-1]==interval).all()):
        raise ValueError("PARENT_PHYSICAL_TIMEGRID_INVALID")
    closings=raw+interval
    match=int(np.searchsorted(closings.asi8,decision.value,side="right")-1)
    if match<0 or match+8>=len(src):raise ValueError("PARENT_NOT_PHYSICALLY_BOUND_AVAILABLE")
    previous=85 if minutes==60 else 35
    if match<previous:raise ValueError("INSUFFICIENT_CAUSAL_PARENT_HISTORY")
    start=match-previous
    # Use eight *actual later parent bars* as an adversarial suffix. At or
    # before the decision instant, all three frames are byte-identical.
    prefix=src.iloc[start:match+1].reset_index(drop=True)
    extended=src.iloc[start:match+9].reset_index(drop=True)
    changed=extended.copy()
    future=changed.index[len(prefix):]
    for col,factor in (("high",2.0),("low",.25),("close",1.25),("volume",3.0)):
        changed.loc[future,col]=changed.loc[future,col].astype(float)*factor
    # Original source chart uses UTC bar OPEN; convert to UTC close in the
    # immutable original _closed_asof, not by swapping timestamps here.
    marker=pd.DataFrame({"decision_at":[decision]})
    label=f"h{minutes}_"
    data=[]
    for sf in (prefix,extended,changed):
        values=context_features(sf,minutes)
        joined=original_merge(sf,minutes*60_000,marker,values,label)
        if len(joined)!=1:raise ValueError("ORIGINAL_ASOF_WRONG_CARDINALITY")
        data.append({k:float(joined[label+k].iat[0]) for k in values})
    oracle={k:float(v.iloc[-1]) for k,v in context_features(prefix,minutes).items()}
    for actual in data:
        if actual!=oracle:raise ValueError("H1_H4_FUTURE_CONTEXT_LEAK_OR_ASOF_WRONG")
    if closings[match]>decision or closings[match+1]<=decision:
        raise ValueError("LATEST_COMPLETED_PARENT_CLOSE_BAD")
    return {
        "decision_utc":decision.isoformat(),
        "timeframe_minutes":minutes,
        "latest_completed_parent_open_utc":raw[match].isoformat(),
        "latest_completed_parent_close_utc":closings[match].isoformat(),
        "next_incomplete_parent_close_utc":closings[match+1].isoformat(),
        "closed_parent_before_or_equal_decision":True,
        "future_parent_not_yet_closed_at_decision":True,
        "original_asof_equals_independent_oracle":True,
        "future_8_parent_bar_append_and_extreme_mutation_invariant":True,
        "h1_h4_context":oracle}

def audit_original_archive(archive,source_root,trace_path):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    import nexus_composite_strategy_research as original
    from nexus_elliott_five_swing_research import PARAMETERS
    source_root=Path(source_root)
    for filename,expected in PARAMETERS["feature_sha256"].items():
        if digest(source_root/filename)!=expected:
            raise ValueError("ORIGINAL_LEGACY_SOURCE_BYTES_CHANGED")
    if digest(trace_path)!=EXPECTED_TRACE:raise ValueError("LEGACY_TRADE_TRACE_CHANGED")
    record=json.loads(Path(trace_path).read_text(encoding="utf8"))
    if record.get("live_enabled") is not False:raise ValueError("NON_RESEARCH_INPUT")
    seen={}
    for cell in record["rows"]:
        for t in cell["trades"]:
            key=(cell["symbol"],cell["part"],int(t["trade_index"]))
            stamped=t["decision"]["decision_at"]
            if key in seen and seen[key]!=stamped:
                raise ValueError("COST_PROFILE_DECISION_MISMATCH")
            seen[key]=stamped
    if len(seen)!=10:raise ValueError("NOT_TEN_LEGACY_TRADES")
    results=[]
    source_frames={}
    for symbol in ("BTCUSDT","ETHUSDT"):
        source_frames[symbol]={}
        for minutes,tf in ((60,"hour1"),(240,"hour4")):
            source_frames[symbol][minutes]=load_verified_archive_frame(archive,symbol,tf)
    for (symbol,part,trade_index),when in sorted(seen.items()):
        for minutes in (60,240):
            result=audit_asof_one(source_frames[symbol][minutes],when,minutes,original._closed_asof)
            results.append(dict(symbol=symbol,partition=part,trade_index=trade_index,**result))
    if len(results)!=20:raise ValueError("INCOMPLETE_PARENT_VERIFICATION")
    return {
        "schema":"nexus.elliott-v73-source-closed-h1-h4-asof-audit.v1",
        "audited_utc":datetime.now(timezone.utc).isoformat(),
        "historical_original_trace_sha256":EXPECTED_TRACE,
        "previously_inspected":True,
        "distinct_decisions":10,
        "parent_checks":20,
        "verified_parent_context_1h_count":10,
        "verified_parent_context_4h_count":10,
        "source_pinned_original_engine":True,
        "parent_suffix_invariant_all_checks":True,
        "all_1h_4h_engine_features_and_lookahead_proven_absent":False,
        "real_market_archive_availability_at_decision_proven":False,
        "real_exchange_fills_proven":False,
        "frozen_v52_scoring":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"new_pnl":None,
        "decisions":results}
def main():
    p=argparse.ArgumentParser()
    for name in ("archive","source_root","trace","output"):
        p.add_argument("--"+name,required=True)
    a=p.parse_args()
    dst=Path(a.output)
    if dst.exists():raise RuntimeError("IMMUTABLE_OUTPUT_ALREADY_EXISTS")
    report=audit_original_archive(a.archive,a.source_root,a.trace)
    dst.write_text(json.dumps(report,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"checked":report["parent_checks"],"unique_trades":report["distinct_decisions"],
       "suffix_invariant":report["parent_suffix_invariant_all_checks"],
       "report_sha256":digest(dst)}))
if __name__=="__main__":main()
