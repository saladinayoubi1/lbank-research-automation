"""V63 historical, read-only ETH first-leg fixed-degree pivot forensics.

Re-examines the already-frozen, source-bound V45/V48/V50 historical evidence,
reproducing V50 strict 3m width-1 -> exact 1m width-3 provenance rule.
Shows each accepted first-leg interior extrema, NOT a trading strategy or
a proposed change to the fixed research configuration.
"""
from __future__ import annotations
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from propose_nested_v49 import _strict_minute_pivots
from propose_degree_v50 import CHILD_MINUTES,COARSE_PIVOT_WIDTH
ROOT=Path(r"E:\NEXUS-QA\elliott-v63-child-forensics-20261016")
SOURCE=Path(r"E:\NEXUS-QA\elliott-v45-source1m-oct08-12-20261016\PROVENANCE_RECEIPT.json")
PARENT=Path(r"E:\NEXUS-QA\elliott-v48-nested-candidate-oct08-12-20261016\SOURCE_BOUND_NESTED_CANDIDATES.json")
PRIOR=Path(r"E:\NEXUS-QA\elliott-v50-fixed-3min-degree-20261016\V50_REAL_DEGREE_QA.json")
def digest(p):
    h=hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda:f.read(1048576),b""):h.update(c)
    return h.hexdigest()
v45=json.loads(SOURCE.read_text(encoding="utf8"))
v48=json.loads(PARENT.read_text(encoding="utf8"))
v50=json.loads(PRIOR.read_text(encoding="utf8"))
if CHILD_MINUTES!=3 or COARSE_PIVOT_WIDTH!=1:
    raise RuntimeError("forensics version not pinned to frozen 3m degree")
if not (v45.get("status")=="PASS_BOTH_PAIRS_SOURCE_BOUND_1M_NOT_STRATEGY"
  and v48.get("status")=="PASS_FIXED_CANDIDATE_DISCOVERY_ONLY_NO_WAVE_COUNT"
  and v50.get("schema")=="nexus.elliott-v50-fixed-3m-degree-audit.v1"):
    raise RuntimeError("frozen source lineage schema not accepted")
original=next(x for x in v45["pairs"] if x["symbol"]=="ETHUSDT")
f=Path(original["parquet_path"])
if digest(f)!=original["parquet_sha256"]:raise RuntimeError("V45 physical source changed")
df=pd.read_parquet(f)
if len(df)!=7200:raise RuntimeError("source 5*1440 minute bars required")
time=pd.DatetimeIndex(pd.to_datetime(df["timestamp"],utc=True)).as_unit("ns")
start=pd.Timestamp("2026-10-08T00:00:00Z")
if time[0]!=start or time[-1]+pd.Timedelta(minutes=1)!=pd.Timestamp("2026-10-13T00:00:00Z"):
    raise RuntimeError("historical source chronology mismatch")
if (np.diff(time.asi8)!=pd.Timedelta(minutes=1).value).any():
    raise RuntimeError("minute source gaps")
q=v48["symbols"]["ETHUSDT"]["candidates"]
if len(q)!=1 or not q[0]["all_nine_parents_source_bound"]:
    raise RuntimeError("cannot identify unique frozen ETH parent")
p0,p1=q[0]["mapped_parent_minute_pivots"][:2]
a,b=int(p0["minute_index"]),int(p1["minute_index"])
if not (a<b and p0["kind"]=="low" and p1["kind"]=="high"):
    raise RuntimeError("first leg parents incorrect")
h=df["high"].to_numpy(float);l=df["low"].to_numpy(float)
source_map={(p.index,p.kind):p for p in _strict_minute_pivots(df)}
if len(h)%CHILD_MINUTES:raise RuntimeError("incomplete 3m group")
bars=len(df)//CHILD_MINUTES
coarseh=h.reshape(bars,CHILD_MINUTES).max(axis=1)
coarsel=l.reshape(bars,CHILD_MINUTES).min(axis=1)
accepted=[];unmatched=0
for i in range(1,bars-1):
    hi=coarseh[i]>coarseh[i-1] and coarseh[i]>coarseh[i+1]
    lo=coarsel[i]<coarsel[i-1] and coarsel[i]<coarsel[i+1]
    if hi==lo:
        if hi:unmatched+=1
        continue
    kind="high" if hi else "low"
    slice1=h[i*3:(i+1)*3] if hi else l[i*3:(i+1)*3]
    extreme=float(coarseh[i] if hi else coarsel[i])
    centers=np.flatnonzero(slice1==extreme)
    if len(centers)!=1:
        unmatched+=1
        continue
    center=i*3+int(centers[0])
    point=source_map.get((center,kind))
    if point is None or point.price!=extreme:
        unmatched+=1
        continue
    if not a<center<b:continue
    confirmed3m=time[(i+2)*3-1]+pd.Timedelta(minutes=1)
    confirmed1m=time[center+3]+pd.Timedelta(minutes=1)
    accepted.append({
        "minute_center_index":int(center),
        "kind":kind,
        "price":str(df["high"].iloc[center] if hi else df["low"].iloc[center]),
        "center_open_utc":time[center].isoformat(),
        "three_minute_right_confirm_close_utc":confirmed3m.isoformat(),
        "one_minute_strict_confirm_close_utc":confirmed1m.isoformat(),
        "first_physical_bar_observable_utc":max(confirmed3m,confirmed1m).isoformat(),
        "same_kind_neighbor":False
    })
if len(accepted)!=6:raise RuntimeError(f"V50 expected 6 strict interior pivots, found {len(accepted)}")
if any(a["kind"]==b["kind"] for a,b in zip(accepted,accepted[1:])):
    raise RuntimeError("strict interior alternating pivot unexpectedly same-kind")
prior=v50["symbols"]["ETHUSDT"]["audits"][0]
if prior["per_leg_raw"]!=[len(accepted)] or prior["per_leg_selected"]!=[len(accepted)]:
    raise RuntimeError("V63 independent leg extrema not consistent with V50")
prices=[float(p0["source_price"])]+[float(x["price"]) for x in accepted]+[float(p1["source_price"])]
moves=[round(prices[i+1]-prices[i],8) for i in range(len(prices)-1)]
report={
  "schema":"nexus.elliott-v63-real-historical-first-leg-fixed-degree-forensics.v1",
  "observed_utc":datetime.now(timezone.utc).isoformat(),
  "historically_inspected":True,
  "symbol":"ETHUSDT","time_window":"2026-10-08/2026-10-13 UTC",
  "source_sha256":digest(f),
  "parent_first_low":{"index":a,"open_utc":p0["minute_center_open_utc"],"price":p0["source_price"]},
  "parent_next_high":{"index":b,"open_utc":p1["minute_center_open_utc"],"price":p1["source_price"]},
  "parent_first_leg_change_usdt_per_eth":str(round(prices[-1]-prices[0],8)),
  "frozen_3m_degree_ratio":"15m / 5 = 3m",
  "frozen_strict_child_count_expected":4,
  "strict_3m_child_interior_count":len(accepted),
  "verified_1m_mapped_interior_pivots":accepted,
  "adjacent_swing_price_changes":moves,
  "observed_min_abs_adjacent_swing":min(abs(x) for x in moves),
  "fixed_segmentation_result":"REJECT_DEGREE_COUNT_MISMATCH_6_VS_4",
  "selective_pivot_deletion_allowed":False,
  "research_only":True,"prospective_holdout":False,
  "complete_elliott":False,"entry_signal":False,
  "paper_eligible":False,"live_enabled":False,"new_pnl":None
}
target=ROOT/"V63_FIRST_LEG_PHYSICAL_CHILD_FORENSICS.json"
if target.exists():raise RuntimeError("immutable forensic report already exists")
target.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
print(json.dumps(report,indent=2,ensure_ascii=False))
print("RESULT_SHA256="+digest(target))
