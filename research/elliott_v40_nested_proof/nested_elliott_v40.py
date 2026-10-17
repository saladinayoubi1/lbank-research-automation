"""NEXUS V40 isolated bounded nested Elliot impulse + zigzag ABC proof.

Causality: completed 1m UTC OHLC, strict width-3 confirmed pivots,
9 alternating higher-degree corners, 5-3-5-3-5 impulse subdivisions,
5-3-5 zigzag ABC subdivisions. One child degree only: NOT full recursive
Elliott and NEVER an entry signal or order authority.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence
import numpy as np
import pandas as pd

RESEARCH_ONLY=True
LIVE_ENABLED=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
COMPLETE_RECURSIVE_CLASSIFIER=False
WIDTH=3
EXPECTED=(5,3,5,3,5,5,3,5)
STEP=pd.Timedelta(minutes=1)

@dataclass(frozen=True)
class ConfirmedPivot:
    kind: str
    index: int
    confirmed_at: int
    price: object

@dataclass(frozen=True)
class NestedProof:
    source_bound: bool
    one_child_degree_validated: bool
    complete_recursive_elliott: bool
    entry_signal: bool
    paper_eligible: bool
    reason: str
    decision_close_utc: str
    pivot_indices: tuple[int,...] = ()

def fail(reason,close):
    return NestedProof(False,False,False,False,False,reason,str(close))

def _decimal(value):
    if isinstance(value,bool):raise ValueError("bool price")
    try:x=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):raise ValueError("price malformed")
    if not x.is_finite() or x<=0:raise ValueError("price nonpositive/nonfinite")
    return x

def _price_geometry_5(prices:Sequence[Decimal], sign:int):
    values=[Decimal(sign)*x for x in prices]
    o,one,two,three,four,five=values
    if not (o<two<one<three and one<four<three<five):return False
    lengths=[one-o,three-two,five-four]
    # Conventional non-shortest third for this narrow non-diagonal model.
    return lengths[1]>min(lengths[0],lengths[2])

def _price_geometry_3(prices:Sequence[Decimal], sign:int):
    values=[Decimal(sign)*x for x in prices]
    a,b,c,d=values
    return a<c<b<d

def check_nested_structure(
    source_1m:pd.DataFrame,
    parent:Sequence[ConfirmedPivot],
    children:Sequence[Sequence[ConfirmedPivot]],
    *,
    decision_close_utc:object,
)->NestedProof:
    """Verify bounded TWO-degree impulse+zigzag witnesses; not a profitable signal.

    Source timestamps mark OPEN and only already completed 1m candles are admitted.
    All pivots must be strict locally confirmed extrema, index+WIDTH < last decision
    index; overlap of adjacent child legs occurs only at a shared endpoint.
    """
    close=pd.Timestamp(decision_close_utc)
    if close.tzinfo is None or close.utcoffset() is None:
        raise ValueError("decision_close_utc must be UTC-aware")
    close=close.tz_convert("UTC")
    if not isinstance(source_1m,pd.DataFrame) or not isinstance(source_1m.index,pd.RangeIndex) or source_1m.index.start!=0 or source_1m.index.step!=1:
        raise ValueError("complete index-zero dataframe required")
    required={"timestamp","open","high","low","close"}
    if not required.issubset(source_1m):raise ValueError("incomplete OHLC source")
    if len(source_1m)<15:raise ValueError("source too short")
    raw_times=source_1m["timestamp"].tolist()
    if any(pd.Timestamp(x).tzinfo is None for x in raw_times):
        raise ValueError("source timestamps not timezone-aware")
    times=pd.DatetimeIndex(pd.to_datetime(raw_times,utc=True,errors="raise"))
    if times.hasnans or not times.is_unique or not times.is_monotonic_increasing:
        raise ValueError("source chronology invalid")
    ns=times.asi8
    if np.any(np.diff(ns)!=STEP.value) or np.any(ns%STEP.value!=0):
        raise ValueError("source 1m grid missing/off-grid")
    if times[-1]+STEP!=close:raise ValueError("source has future or incomplete last candle")
    data=source_1m[["open","high","low","close"]].to_numpy(float)
    if not np.isfinite(data).all() or (data<=0).any():
        raise ValueError("invalid OHLC numeric")
    if (data[:,1]<np.maximum.reduce((data[:,0],data[:,2],data[:,3]))).any() or (data[:,2]>np.minimum.reduce((data[:,0],data[:,1],data[:,3]))).any():
        raise ValueError("invalid candle extrema")
    n=len(source_1m)
    if len(parent)!=9 or len(children)!=8:
        return fail("PARENT_OR_ABC_OR_LEGS_MISSING",close.isoformat())
    seen_indices=set()
    def validate_pivot(p:ConfirmedPivot):
        if not isinstance(p,ConfirmedPivot) or p.kind not in ("low","high") or type(p.index) is not int or type(p.confirmed_at) is not int:
            raise ValueError("pivot evidence malformed")
        at=p.index
        if not WIDTH<=at<n-WIDTH:raise ValueError("pivot missing context")
        if p.confirmed_at!=at+WIDTH or p.confirmed_at>=n-1:
            raise ValueError("pivot not causally confirmed strictly before decision")
        price=_decimal(p.price)
        h=data[:,1];l=data[:,2]
        hi=float(h[at]);lo=float(l[at])
        high_local=all(hi>h[j] for j in range(at-WIDTH,at+WIDTH+1) if j!=at)
        low_local=all(lo<l[j] for j in range(at-WIDTH,at+WIDTH+1) if j!=at)
        if high_local==low_local:raise ValueError("pivot tied or ambiguous outside candle")
        if p.kind=="high" and (not high_local or Decimal(str(hi))!=price):raise ValueError("claimed high not source bound")
        if p.kind=="low" and (not low_local or Decimal(str(lo))!=price):raise ValueError("claimed low not source bound")
        return price
    try:
        if any(p.kind!=("low" if i%2==0 else "high") for i,p in enumerate(parent)):
            return fail("PARENT_POLARITY_INVALID",close.isoformat())
        if any(b.index<=a.index for a,b in zip(parent,parent[1:])):
            return fail("PARENT_CHRONOLOGY_INVALID",close.isoformat())
        parents=[validate_pivot(x) for x in parent]
        if not _price_geometry_5(parents[:6],1):
            return fail("IMPULSE_PARENT_GEOMETRY_FAILED",close.isoformat())
        if not (parents[6]<parents[7]<parents[5] and parents[8]<parents[6]):
            return fail("ABC_ZIGZAG_PARENT_GEOMETRY_FAILED",close.isoformat())
        all_members=[]
        for i,count in enumerate(EXPECTED):
            segment=children[i]
            if len(segment)!=count+1:
                return fail(f"SUBWAVE_COUNT_IN_LEG_{i}",close.isoformat())
            if segment[0]!=parent[i] or segment[-1]!=parent[i+1]:
                return fail(f"SUBWAVE_PARENT_ENDPOINT_MISMATCH_{i}",close.isoformat())
            if any(b.index<=a.index for a,b in zip(segment,segment[1:])):
                return fail(f"CHILD_CHRONOLOGY_IN_LEG_{i}",close.isoformat())
            expected_first="low" if i%2==0 else "high"
            if any(p.kind!= (expected_first if j%2==0 else ("high" if expected_first=="low" else "low")) for j,p in enumerate(segment)):
                return fail(f"CHILD_POLARITY_IN_LEG_{i}",close.isoformat())
            numbers=[validate_pivot(p) for p in segment]
            sign=1 if i%2==0 else -1
            if (count==5 and not _price_geometry_5(numbers,sign)) or (count==3 and not _price_geometry_3(numbers,sign)):
                return fail(f"CHILD_GEOMETRY_IN_LEG_{i}",close.isoformat())
            all_members.extend(segment[:-1])
        all_members.append(parent[-1])
        indices=[p.index for p in all_members]
        if len(set(indices))!=len(indices):
            return fail("NONLOCAL_CHILD_OVERLAP",close.isoformat())
        if not all(a<b for a,b in zip(indices,indices[1:])):
            return fail("NONMONOTONIC_CHILD_CHRONOLOGY",close.isoformat())
    except (TypeError,ValueError,InvalidOperation) as e:
        return fail("SOURCE_PIVOT_REJECTED:"+str(e),close.isoformat())
    return NestedProof(True,True,False,False,False,
                       "ONE_CHILD_DEGREE_BOUNDED_5_3_5_3_5_PLUS_ZIGZAG_ABC_ONLY",
                       close.isoformat(),tuple(p.index for p in parent))
