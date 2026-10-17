"""V66 retrospective V65 vertex provenance check; never a trading signal.

Only historical Oct08-12 Bybit ETHUSDT Spot physical 1m archive previously
inspected by V45/V46/V48/V63. No new unseen forward observations. Rebuilds
strict width-3 1m pivots, strict 3m width-1 pivots and strict width-3 15m
parent endpoints before asking V65 geometric grammar about each vertex.
"""
from __future__ import annotations
import argparse
import copy
from datetime import timezone,datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from nexus_causal_elliott_five_swing_features import _confirmed_pivot
from propose_nested_v49 import _strict_minute_pivots
from grammar_v65 import Vertex, assess_seven_moves

RESEARCH_ONLY=True
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
LIVE_ENABLED=False
HISTORICALLY_INSPECTED=True
ETH_1M_SHA="fbdad48b85ff5ada62c2e12e3321413fdf60ddf5b5655df68d5b60e98c1cdfcf"
V63_RECEIPT_SHA="51d742a3a487e1a416e79e8319df87b2a954075f77d4a455b43a5c67bbac1585"
START=pd.Timestamp("2026-10-08T00:00:00Z")
END=pd.Timestamp("2026-10-13T00:00:00Z")

def hash_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1048576),b""):h.update(block)
    return h.hexdigest()

def strict_utc(value):
    stamp=pd.Timestamp(value)
    if stamp.tzinfo is None or stamp.utcoffset() is None:raise ValueError("NAIVE_TIMESTAMP")
    return stamp.tz_convert("UTC")

def verify_historical_vertices(df,receipt):
    """Reconstruct, never trust user-supplied receipt values without source."""
    if receipt.get("schema")!="nexus.elliott-v63-real-historical-first-leg-fixed-degree-forensics.v1":
        raise ValueError("V63_RECEIPT_SCHEMA_MISMATCH")
    if receipt.get("source_sha256")!=ETH_1M_SHA:
        raise ValueError("V63_SOURCE_LINEAGE_MISMATCH")
    if (receipt.get("strict_3m_child_interior_count")!=6 or
        receipt.get("frozen_strict_child_count_expected")!=4 or
        receipt.get("selective_pivot_deletion_allowed") is not False or
        receipt.get("entry_signal") is not False or
        receipt.get("live_enabled") is not False):
        raise ValueError("V63_IMMUTABLE_CHILD_RULE_MISMATCH")
    if len(df)!=7200 or not {"timestamp","open","high","low","close"}.issubset(df):
        raise ValueError("NOT_FULL_PHYSICAL_FIVE_DAY_SOURCE")
    if any(pd.Timestamp(x).tzinfo is None for x in df["timestamp"]):
        raise ValueError("SOURCE_TIMESTAMP_NAIVE")
    times=pd.DatetimeIndex(pd.to_datetime(df["timestamp"],utc=True)).as_unit("ns")
    expected=pd.date_range(START,periods=7200,freq="min",tz="UTC").as_unit("ns")
    if not times.equals(expected) or times[-1]+pd.Timedelta(minutes=1)!=END:
        raise ValueError("SOURCE_1M_GRID_MISSING_OR_FUTURE")
    vals=df[["open","high","low","close"]].to_numpy(float)
    if (not np.isfinite(vals).all() or (vals<=0).any() or
        (vals[:,1]<np.max(vals,axis=1)).any() or
        (vals[:,2]>np.min(vals,axis=1)).any()):
        raise ValueError("SOURCE_OHLC_INVALID")
    hi=vals[:,1];lo=vals[:,2]
    strict={(p.index,p.kind):p for p in _strict_minute_pivots(df)}
    coarsehi=hi.reshape(-1,3).max(axis=1)
    coarselo=lo.reshape(-1,3).min(axis=1)
    parenthi=hi.reshape(-1,15).max(axis=1)
    parentlo=lo.reshape(-1,15).min(axis=1)
    first=receipt["parent_first_low"];last=receipt["parent_next_high"]
    interior=receipt["verified_1m_mapped_interior_pivots"]
    if len(interior)!=6:raise ValueError("RECEIPT_INTERIOR_COUNT")
    rows=[
      (int(first["index"]),"low",str(first["price"]),first["open_utc"],None,first),
      *[(int(x["minute_center_index"]),x["kind"],str(x["price"]),x["center_open_utc"],"child",x) for x in interior],
      (int(last["index"]),"high",str(last["price"]),last["open_utc"],None,last),
    ]
    if tuple(x[1] for x in rows)!=("low","high","low","high","low","high","low","high"):
        raise ValueError("VERTEX_POLARITY_MISMATCH")
    if any(b[0]<=a[0] for a,b in zip(rows,rows[1:])):
        raise ValueError("VERTEX_CHRONOLOGY_MISMATCH")
    vertices=[];child_times=[];parent_times=[];evidence=[]
    for idx,kind,price,center_stamp,level,item in rows:
        if not 3<=idx<len(df)-4:raise ValueError("VERTEX_OUT_OF_1M_CONTEXT")
        if times[idx]!=strict_utc(center_stamp):
            raise ValueError("VERTEX_CENTER_TIMESTAMP_MISMATCH")
        witness=strict.get((idx,kind))
        source_price=Decimal(str(hi[idx] if kind=="high" else lo[idx]))
        if witness is None or Decimal(str(witness.price))!=Decimal(price) or source_price!=Decimal(price):
            raise ValueError("VERTEX_PRICE_OR_STRICT_1M_PIVOT_MISMATCH")
        if witness.confirmed_at!=idx+3:raise ValueError("VERTEX_1M_RIGHT_CONFIRM_MISMATCH")
        confirmed_1m=times[idx+3]+pd.Timedelta(minutes=1)
        if level=="child":
            ci=idx//3
            is_hi=bool(coarsehi[ci]>coarsehi[ci-1] and coarsehi[ci]>coarsehi[ci+1])
            is_lo=bool(coarselo[ci]<coarselo[ci-1] and coarselo[ci]<coarselo[ci+1])
            if (is_hi==is_lo or (kind=="high")!=is_hi):
                raise ValueError("CHILD_NOT_STRICT_3M_PIVOT")
            local=hi[ci*3:(ci+1)*3] if is_hi else lo[ci*3:(ci+1)*3]
            coarse_price=coarsehi[ci] if is_hi else coarselo[ci]
            if np.count_nonzero(local==coarse_price)!=1 or float(coarse_price)!=float(price):
                raise ValueError("CHILD_3M_ORIGIN_AMBIGUOUS")
            confirmed_3m=times[(ci+2)*3-1]+pd.Timedelta(minutes=1)
            physical_confirm=max(confirmed_1m,confirmed_3m)
            if (strict_utc(item["one_minute_strict_confirm_close_utc"])!=confirmed_1m or
                strict_utc(item["three_minute_right_confirm_close_utc"])!=confirmed_3m or
                strict_utc(item["first_physical_bar_observable_utc"])!=physical_confirm):
                raise ValueError("CHILD_CONFIRMATION_TIME_MISMATCH")
            child_times.append(physical_confirm)
        else:
            pi=idx//15
            parent_pivot=_confirmed_pivot(parenthi,parentlo,pi+3)
            if (parent_pivot is None or parent_pivot.index!=pi or
                parent_pivot.kind!=kind or parent_pivot.price!=float(price)):
                raise ValueError("PARENT_NOT_STRICT_15M_SOURCE_PIVOT")
            confirmed_15m=times[(pi+4)*15-1]+pd.Timedelta(minutes=1)
            parent_times.append(confirmed_15m)
        vertices.append(Vertex(int(idx),kind,str(price)))
        evidence.append({"index":idx,"kind":kind,"source_price":str(price),
                         "strict_1m_confirm_close_utc":confirmed_1m.isoformat()})
    geom=assess_seven_moves(tuple(vertices))
    earliest=max(parent_times+child_times)
    return {
        "vertex_count":len(vertices),
        "physically_attested_historical_vertices":True,
        "confirmed_1m_count":len(vertices),
        "confirmed_3m_interior_count":len(child_times),
        "confirmed_15m_parent_count":len(parent_times),
        "latest_child_3m_confirm_close_utc":max(child_times).isoformat(),
        "parent_15m_confirm_closes_utc":[x.isoformat() for x in parent_times],
        "first_structural_pivot_decision_not_before_utc":earliest.isoformat(),
        "five_leg_nested_abc_expansions":[
            {"name":x.name,"parent_impulse":x.five_leg_impulse_geometry,
             "child_downward_zigzag":x.countertrend_abc_zigzag_geometry,
             "joint_accept":x.accepted} for x in geom.expansions],
        "geometry_state":geom.state,
        "geometry_valid_expansions":geom.valid_expansion_count,
        "strict_source_pivot_evidence":evidence,
        "source_archive_accessible_at_structural_time":False,
        "executable_quote_proof":False,"retrospective_history_only":True,
        "entry_signal":False,"paper_eligible":False,"live_enabled":False,
        "pnl":None
    }

def audit_files(source,receipt):
    if hash_file(source)!=ETH_1M_SHA:raise ValueError("PHYSICAL_SOURCE_SHA_MISMATCH")
    if hash_file(receipt)!=V63_RECEIPT_SHA:raise ValueError("V63_RECEIPT_SHA_MISMATCH")
    data=pd.read_parquet(source)
    spec=json.loads(Path(receipt).read_text(encoding="utf-8"))
    return data,spec,verify_historical_vertices(data,spec)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--source",required=True)
    parser.add_argument("--receipt",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    df,receipt,proof=audit_files(args.source,args.receipt)
    # Mutation tests exercise source-level corroboration, not only file hashes.
    for label,mutate in (
      ("fabricated_last_child_price", lambda r:r["verified_1m_mapped_interior_pivots"][-1].update(price="2496.66")),
      ("fabricated_child_confirm", lambda r:r["verified_1m_mapped_interior_pivots"][1].update(first_physical_bar_observable_utc="2026-10-10T09:05:00+00:00")),
      ("fabricated_parent_price", lambda r:r["parent_first_low"].update(price="2492.77")),
      ("backdated_parent_center", lambda r:r["parent_next_high"].update(open_utc="2026-10-10T09:30:00+00:00")),
    ):
        altered=copy.deepcopy(receipt);mutate(altered)
        try:verify_historical_vertices(df,altered)
        except ValueError:pass
        else:raise RuntimeError("MUTANT_WRONGLY_ACCEPTED:"+label)
    result={"schema":"nexus.elliott-v66-history-only-hierarchy-physical-reattest.v1",
            "observed_utc":datetime.now(timezone.utc).isoformat(),
            "verified_source_sha256":ETH_1M_SHA,
            "verified_v63_receipt_sha256":V63_RECEIPT_SHA,
            "adversarial_mutation_rejections":4,
            **proof}
    out=Path(args.output)
    if out.exists():raise RuntimeError("IMMUTABLE_RECEIPT_EXISTS")
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print(json.dumps({"status":"PASS_HISTORICAL_PHYSICAL_WITNESSES_ONLY",
        "geometry_state":result["geometry_state"],
        "earliest_structure":result["first_structural_pivot_decision_not_before_utc"],
        "mutants_rejected":4,"sha256":hash_file(out)},ensure_ascii=False))
if __name__=="__main__":main()
