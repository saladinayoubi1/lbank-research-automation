"""V72 source-bound future suffix and prefix invariance audit of LEGACY Elliott.

This is a retrospective diagnostic over a physically verified Bybit 15m
archive and the frozen V37 legacy simulated fill trace. It is NOT a full
independent future-data leakage proof for the entire engine, nor a trade.
No source, optimizer, paper wallet, or installed runner is modified.
"""
from __future__ import annotations
import argparse
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd

EXPECTED_TRACE="c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c"
RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
ARCHIVE_FEATURE_SUFFIX_BARS=12
PREFIX_HISTORY_BARS=1024

def hashfile(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda:f.read(1048576),b""):h.update(part)
    return h.hexdigest()

def _field_equal(left,right):
    if tuple(left.keys())!=tuple(right.keys()):return False
    for key in left:
        a=left[key].to_numpy()
        b=right[key].to_numpy()[:len(a)]
        if len(a)>len(b):return False
        if not np.array_equal(a,b,equal_nan=True):
            # np.array_equal(equal_nan=True) may not accept nullable bool
            try:
                if not np.allclose(a.astype(float),b.astype(float),
                                   rtol=0,atol=0,equal_nan=True):
                    return False
            except (TypeError,ValueError):
                return False
    return True

def five_swing_prefix_check(frame,decision_index,feature_builder):
    if type(decision_index) is not int or not (PREFIX_HISTORY_BARS<=decision_index<len(frame)-ARCHIVE_FEATURE_SUFFIX_BARS):
        raise ValueError("INVALID_PREFIX_SNAPSHOT_WINDOW")
    a=decision_index-PREFIX_HISTORY_BARS+1
    basic=frame.iloc[a:decision_index+1].copy().reset_index(drop=True)
    more=frame.iloc[a:decision_index+1+ARCHIVE_FEATURE_SUFFIX_BARS].copy().reset_index(drop=True)
    baseline=feature_builder(basic)
    extended=feature_builder(more)
    if not _field_equal(baseline,extended):
        raise ValueError("FUTURE_UNMODIFIED_SUFFIX_CHANGED_PAST_FEATURE")
    modified=more.copy()
    future=slice(len(basic),len(more))
    modified.loc[modified.index[future],"high"]=modified.loc[modified.index[future],"high"]*1.8
    modified.loc[modified.index[future],"low"]=modified.loc[modified.index[future],"low"]*0.4
    if not _field_equal(baseline,feature_builder(modified)):
        raise ValueError("FUTURE_TAMPERED_SUFFIX_CHANGED_PAST_FEATURE")
    j=len(basic)-1
    present=bool(baseline["elliott5_close_breakout_event"].iat[j])
    confirmed=baseline["lagged_elliott5_confirmed_at"].iat[j]
    if present and (not np.isfinite(confirmed) or confirmed>=j):
        raise ValueError("EVENT_NOT_STRICTLY_PREVIOUSLY_PIVOT_CONFIRMED")
    return dict(feature_count=len(baseline),asof_event=present,
                setup_active=bool(baseline["lagged_elliott5_active"].iat[j]),
                strictly_past_confirmed=bool(present and confirmed<j),
                original_and_mutated_future_unchanged=True)

def audit(archive,trace_path,source_root):
    from nexus_multitimeframe_verified_archive_discovery import load_verified_archive_frame
    from nexus_causal_elliott_five_swing_features import build_lagged_elliott_five_swing_features
    from nexus_elliott_five_swing_research import PARAMETERS
    trace_path=Path(trace_path);source_root=Path(source_root)
    if hashfile(trace_path)!=EXPECTED_TRACE:raise ValueError("FROZEN_TRACE_CHANGED")
    for name,expected in PARAMETERS["feature_sha256"].items():
        if hashfile(source_root/name)!=expected:raise ValueError("ORIGINAL_FEATURE_SOURCE_CHANGED")
    if PARAMETERS["live_enabled"] is not False or PARAMETERS["auto_demo_promotion"] is not False:
        raise ValueError("LEGACY_RESEARCH_SCOPE_INVALID")
    t=json.loads(trace_path.read_text(encoding="utf8"))
    if t.get("live_enabled") is not False:raise ValueError("TRADE_TRACE_LIVE_AUTHORITY")
    items={}
    for row in t["rows"]:
        for trade in row["trades"]:
            key=(row["symbol"],row["part"],int(trade["trade_index"]))
            idx=int(trade["decision"]["bar_index"])
            if key in items and idx!=items[key]["decision_index"]:
                raise ValueError("COST_PROFILE_DECISION_DISAGREEMENT")
            items[key]=dict(symbol=row["symbol"],partition=row["part"],
                            trade_id=int(trade["trade_index"]),
                            decision_index=idx,
                            recorded_decision_utc=trade["decision"]["decision_at"])
    if len(items)!=10:raise ValueError("EXPECTED_TEN_LEGACY_UNIQUE_DECISIONS")
    files={}
    results=[]
    for sym in ("BTCUSDT","ETHUSDT"):
        original=load_verified_archive_frame(archive,sym,"minute15")
        close=pd.to_datetime(original["timestamp"],utc=True)+pd.Timedelta(minutes=15)
        frame=original[["open","high","low","close"]].copy()
        frame["timestamp"]=close
        files[sym]=frame
    for key,item in sorted(items.items()):
        frame=files[item["symbol"]]
        index=item["decision_index"]
        expected=pd.Timestamp(item["recorded_decision_utc"]).tz_convert("UTC")
        if frame["timestamp"].iloc[index]!=expected:
            raise ValueError("RECORDED_LEGACY_DECISION_NOT_PHYSICAL_BAR_CLOSE")
        checked=five_swing_prefix_check(frame,index,build_lagged_elliott_five_swing_features)
        if not checked["asof_event"] or not checked["setup_active"] or not checked["strictly_past_confirmed"]:
            raise ValueError("REPORTED_LEGACY_FILLED_TRADE_NOT_CAUSAL_ELLIOTT_EVENT_IN_PREFIX")
        results.append({**item,**checked})
    return {
        "schema":"nexus.elliott-v72-legacy-physical-prefix-invariance.v1",
        "frozen_legacy_trace_sha256":EXPECTED_TRACE,
        "historical_research_only":True,
        "previously_inspected":True,
        "source_archive":"pinned_original_bybit_verified_15m",
        "unique_trade_decisions":len(items),
        "source_verified_pairs":2,
        "prefix_bars_per_decision":PREFIX_HISTORY_BARS+1,
        "future_suffix_bars_checked":ARCHIVE_FEATURE_SUFFIX_BARS,
        "source_prefix_unchanged_under_future_append_and_mutation":True,
        "source_level_all_engine_feature_leakage_proven_absent":False,
        "future_V52_holdout_evidence":False,
        "paper_eligible":False,"live_enabled":False,"entry_signal":False,
        "filled_demo_trades":0,"new_pnl":None,
        "per_decision":results
    }

def main():
    p=argparse.ArgumentParser()
    for name in ("archive","trace","source_root","output"):
        p.add_argument("--"+name,required=True)
    a=p.parse_args()
    dst=Path(a.output)
    if dst.exists():raise RuntimeError("IMMUTABLE_RECEIPT_EXISTS")
    result=audit(a.archive,a.trace,a.source_root)
    dst.write_text(json.dumps(result,indent=2)+"\n",encoding="utf8")
    print(json.dumps(dict(count=result["unique_trade_decisions"],
          matched=sum(v["asof_event"] for v in result["per_decision"]),
          confirmed=sum(v["strictly_past_confirmed"] for v in result["per_decision"]),
          suffix_unchanged=result["source_prefix_unchanged_under_future_append_and_mutation"],
          sha256=hashfile(dst))))
if __name__=="__main__":main()
