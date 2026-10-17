"""V74: read-only complete legacy composite feature future-leak audit.

Uses original immutable Bybit archived OHLC and original unmodified engine.
For each frozen historical simulated Elliott decision, compare ALL returned
composite engine features on a fixed source prefix with 12 added future 15m
and eight future H1/H4 bars, then with future-only extreme price tampering.
This is historical prefix invariance, not an all-market/production proof.
No trade, Demo, Live, or P/L.
"""
from __future__ import annotations
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
import argparse,json
import numpy as np
import pandas as pd

TRACE_SHA="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
BASE_15M=1152
FUTURE_15M=12
FUTURE_PARENTS=8
BASE_PARENTS={60:420,240:160}
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False

def digest(path):
    h=sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(1048576),b""):h.update(b)
    return h.hexdigest()

def compare_prefix(baseline,other,kind):
    if len(other)<len(baseline):raise ValueError("COMPOSITE_ROW_COUNT_MISSING")
    try:
        pd.testing.assert_frame_equal(baseline.reset_index(drop=True),
            other.iloc[:len(baseline)].reset_index(drop=True),
            check_exact=True,check_dtype=True,check_index_type=True)
    except AssertionError as exc:
        # Never silently accept a feature or timestamp re-written by future bars.
        raise ValueError("COMPOSITE_FUTURE_LEAK_"+kind+": "+str(exc)[:500]) from exc
    return len(baseline.columns)

def closed_prefix(frame,when,tf):
    mins={"minute15":15,"hour1":60,"hour4":240}[tf]
    opens=pd.DatetimeIndex(pd.to_datetime(frame["timestamp"],utc=True))
    duration=pd.Timedelta(minutes=mins)
    if not opens.is_monotonic_increasing or not opens.is_unique:
        raise ValueError("SOURCE_TIMESTAMP_NOT_ORDERED")
    if not (opens[1:]-opens[:-1]==duration).all():
        raise ValueError("SOURCE_TIME_GRID_BROKEN")
    end=int(np.searchsorted((opens+duration).asi8,when.value,side="right"))
    needed=BASE_15M if tf=="minute15" else BASE_PARENTS[mins]+1
    if end<needed or len(frame)<end+(FUTURE_15M if tf=="minute15" else FUTURE_PARENTS):
        raise ValueError("INSUFFICIENT_FROZEN_SOURCE_FOR_DECISION")
    start=end-needed
    baseline=frame.iloc[start:end].copy().reset_index(drop=True)
    append=FUTURE_15M if tf=="minute15" else FUTURE_PARENTS
    extended=frame.iloc[start:end+append].copy().reset_index(drop=True)
    future=extended.index[len(baseline):]
    changed=extended.copy()
    for col,factor in (("high",2.0),("low",0.3),("close",1.4),("volume",4.0)):
        changed.loc[future,col]=changed.loc[future,col].astype(float)*factor
    # Verify changed future still has physically allowable synthetic OHLC.
    if ((changed.loc[future,"high"]<changed.loc[future,["open","close","low"]].max(axis=1)).any()
            or (changed.loc[future,"low"]>changed.loc[future,["open","close","high"]].min(axis=1)).any()):
        raise ValueError("FUTURE_TAMPERED_SOURCE_INVALID_OHLC")
    if pd.Timestamp(baseline["timestamp"].iat[-1]).tz_convert("UTC")+duration>when:
        raise ValueError("PARENT_CANDLE_NOT_CLOSED_AT_DECISION")
    if pd.Timestamp(extended["timestamp"].iat[len(baseline)]).tz_convert("UTC")+duration<=when:
        raise ValueError("FUTURE_BAR_ALREADY_CLOSED_BAD_SPLIT")
    return baseline,extended,changed

def evaluate_at(frames,when,feature_builder):
    when=pd.Timestamp(when)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("DECISION_NOT_UTC_AWARE")
    when=when.tz_convert("UTC")
    variants={v:{} for v in ("baseline","extended","altered_future")}
    for timeframe,df in frames.items():
        src=closed_prefix(df,when,timeframe)
        for mode,sub in zip(variants,src):
            variants[mode][timeframe]=sub
    base=feature_builder(variants["baseline"])
    future=feature_builder(variants["extended"])
    changed=feature_builder(variants["altered_future"])
    n=compare_prefix(base,future,"APPENDED")
    compare_prefix(base,changed,"MUTATED")
    if len(base)!=BASE_15M or pd.Timestamp(base["decision_at"].iat[-1]).tz_convert("UTC")!=when:
        raise ValueError("LAST_DECISION_NOT_ARCHIVE_CLOSE")
    return {"columns":n,"rows":len(base),"future_15m":FUTURE_15M,
            "future_parent_each":FUTURE_PARENTS,"all_earlier_feature_cells_unchanged":True,
            "final_decision_at_utc":when.isoformat()}

def audit_files(archive,source_root,trace_path):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    from nexus_elliott_five_swing_research import PARAMETERS
    from nexus_composite_strategy_research import build_features
    root=Path(source_root)
    for filename,dig in PARAMETERS["feature_sha256"].items():
        if digest(root/filename)!=dig:
            raise ValueError("ORIGINAL_FROZEN_ENGINE_HASH_CHANGED")
    if digest(trace_path)!=TRACE_SHA:raise ValueError("ORIGINAL_TRACE_HASH_CHANGED")
    record=json.loads(Path(trace_path).read_text(encoding="utf8"))
    if record.get("live_enabled") is not False:
        raise ValueError("TRACE_NOT_RESEARCH_ONLY")
    decisions={}
    for block in record["rows"]:
        for trade in block["trades"]:
            key=(block["symbol"],block["part"],int(trade["trade_index"]))
            stamp=trade["decision"]["decision_at"]
            if key in decisions and decisions[key]!=stamp:
                raise ValueError("COST_PROFILE_DECISION_DIFFERENCE")
            decisions[key]=stamp
    if len(decisions)!=10:raise ValueError("EXPECTED_TEN_FROZEN_DECISIONS")
    market={}
    for sym in ("BTCUSDT","ETHUSDT"):
        market[sym]={tf:load_verified_archive_frame(archive,sym,tf)
                     for tf in ("minute15","hour1","hour4")}
    output=[]
    for (symbol,part,trade_index),instant in sorted(decisions.items()):
        observed=evaluate_at(market[symbol],instant,build_features)
        output.append({"symbol":symbol,"partition":part,"trade_id":trade_index,
                       **observed})
    counts=set(x["columns"] for x in output)
    return {
        "schema":"nexus.elliott-v74-legacy-full-composite-prefix-check.v1",
        "audited_utc":datetime.now(timezone.utc).isoformat(),
        "historically_inspected":True,
        "original_sha_pinned_trace":TRACE_SHA,
        "unique_decisions":len(output),
        "composite_feature_column_counts":sorted(counts),
        "all_10_original_decisions_append_mutate_invariant":True,
        "source_verified_timeframes":["15m","1h","4h"],
        "full_original_legacy_engine_proven_for_every_market_bar":False,
        "real_quote_and_fill_proven":False,
        "new_v52_holdout_proven":False,
        "entry_signal":False,"paper_eligible":False,
        "live_enabled":False,"new_pnl":None,
        "checks":output}
def main():
    p=argparse.ArgumentParser()
    for name in ("archive","source_root","trace","output"):p.add_argument("--"+name,required=True)
    a=p.parse_args()
    result=audit_files(a.archive,a.source_root,a.trace)
    dst=Path(a.output)
    if dst.exists():raise RuntimeError("IMMUTABLE_AUDIT_ALREADY_EXISTS")
    dst.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps({"verified_decisions":result["unique_decisions"],
       "columns":result["composite_feature_column_counts"],"sha256":digest(dst)}))
if __name__=="__main__":main()
