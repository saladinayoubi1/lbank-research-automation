"""V61 historical as-of 15m Elliott parent discovery replay.

Rechecks frozen, previously inspected V45 source-bound BTC/ETH October 8-12
1m hashes, reconstructs 15m strict-causal pivots one closed bar at a time.
Compares final census to frozen V48 receipt. NOT prospective, no entries/P&L.
"""
from __future__ import annotations
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import pandas as pd
from nexus_causal_elliott_five_swing_features import _confirmed_pivot
from nested_elliott_v40 import _price_geometry_5

ROOT=Path(r"E:\NEXUS-QA\elliott-v61-parent-replay-20261016")
V45=Path(r"E:\NEXUS-QA\elliott-v45-source1m-oct08-12-20261016\PROVENANCE_RECEIPT.json")
V48=Path(r"E:\NEXUS-QA\elliott-v48-nested-candidate-oct08-12-20261016\SOURCE_BOUND_NESTED_CANDIDATES.json")
START=pd.Timestamp("2026-10-08T00:00:00Z")
END=pd.Timestamp("2026-10-13T00:00:00Z")
SRC=dict((p["symbol"],p) for p in json.loads(V45.read_text(encoding="utf8"))["pairs"])
FROZEN=json.loads(V48.read_text(encoding="utf8"))["symbols"]
EXPECT=("low","high","low","high","low","high","low","high","low")
def sha(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for ch in iter(lambda:f.read(1048576),b""):h.update(ch)
    return h.hexdigest()
def valid_parent_shape(p):
    if len(p)!=9 or tuple(x.kind for x in p)!=EXPECT:return False
    nums=[Decimal(str(x.price)) for x in p]
    return bool(_price_geometry_5(nums[:6],1) and nums[6]<nums[7]<nums[5] and nums[8]<nums[6])
def key(p):return tuple(x.index for x in p)
def parent_window(pivots):
    return [pivots[i:i+9] for i in range(max(0,len(pivots)-8))
            if valid_parent_shape(pivots[i:i+9])]
def one(symbol):
    spec=SRC[symbol]
    source=Path(spec["parquet_path"])
    observed=sha(source)
    if observed!=spec["parquet_sha256"]:raise RuntimeError("V45 physical SHA mismatch")
    frame=pd.read_parquet(source)
    if len(frame)!=7200:raise RuntimeError("V45 source missing 7200 true minutes")
    t=pd.DatetimeIndex(pd.to_datetime(frame["timestamp"],utc=True))
    if t[0]!=START or t[-1]+pd.Timedelta(minutes=1)!=END:
        raise RuntimeError("wrong V45 source window")
    if (t[1:]-t[:-1]!=pd.Timedelta(minutes=1)).any():
        raise RuntimeError("V45 missing 1m source grid")
    ohlc=frame.set_index(t).resample("15min",label="left",closed="left",origin="start_day").agg(
       open=("open","first"),high=("high","max"),low=("low","min"),
       close=("close","last"),volume=("volume","sum"))
    if len(ohlc)!=480:raise RuntimeError("expected 480 closed 15m bars")
    h=ohlc["high"].to_numpy(float);l=ohlc["low"].to_numpy(float)
    selected=[];ever={};events=[];replacement_count=0
    for at in range(len(ohlc)):
        pivot=_confirmed_pivot(h,l,at)
        if pivot is not None:
            if selected and selected[-1].kind==pivot.kind:
                prev=selected[-1]
                better=pivot.price>prev.price if pivot.kind=="high" else pivot.price<prev.price
                if better:
                    selected[-1]=pivot
                    replacement_count+=1
            else:selected.append(pivot)
        new=parent_window(selected)
        decision=ohlc.index[at]+pd.Timedelta(minutes=15)
        for group in new:
            fingerprint="|".join(str(z.index)+":"+z.kind+":"+str(z.price) for z in group)
            if fingerprint not in ever:
                ever[fingerprint]={
                    "first_observed_utc":decision.isoformat(),
                    "latest_parent_center_15m":group[-1].index,
                    "latest_parent_confirmed_at_15m":group[-1].confirmed_at,
                    "parent_centers_15m":list(key(group))
                }
                if group[-1].confirmed_at>at:
                    raise RuntimeError("future parent used in causal event")
                events.append(ever[fingerprint])
    final=parent_window(selected)
    frozen=FROZEN[symbol]
    expected=len(frozen["candidates"])
    final_list=[list(key(x)) for x in final]
    frozen_list=[x["parent_centers_15m"] for x in frozen["candidates"]]
    if len(selected)!=frozen["accepted_parent_15m_pivots"]:
        raise RuntimeError("V61 vs V48 parent census mismatch: "+symbol)
    if sorted(final_list)!=sorted(frozen_list) or len(final)!=expected:
        raise RuntimeError("V61 vs V48 frozen nine-parent matches differ: "+symbol)
    return {"symbol":symbol,"source_sha256":observed,
            "closed_15m_bars":len(ohlc),
            "final_accepted_parent_pivots":len(selected),
            "same_kind_replacements_observed":replacement_count,
            "final_frozen_reconstructed_geometries":final_list,
            "ever_seen_causal_nine_parent_events":events,
            "ever_seen_causal_count":len(events),
            "final_census_nine_parent_count":len(final),
            "first_observed_event_after_last_parent_right_bar":all(
               pd.Timestamp(x["first_observed_utc"])>=ohlc.index[x["latest_parent_confirmed_at_15m"]]+pd.Timedelta(minutes=15)
               for x in events)}
records={x:one(x) for x in ("BTCUSDT","ETHUSDT")}
receipt={"schema":"nexus.elliott-v61-history-only-15m-causal-replay.v1",
         "created_utc":datetime.now(timezone.utc).isoformat(),
         "historically_inspected":True,
         "source_start_inclusive_utc":str(START),
         "source_end_exclusive_utc":str(END),
         "source_bound":True,"forward_holdout_scored":False,
         "entry_signal":False,"paper_eligible":False,
         "live_enabled":False,"pnl":None,"symbols":records}
out=ROOT/"V61_REAL_HISTORY_CAUSAL_REPLAY.json"
if out.exists():raise RuntimeError("immutable V61 receipt exists")
out.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
print(json.dumps(records,indent=2,ensure_ascii=False))
print("RECEIPT_SHA256 "+sha(out))
