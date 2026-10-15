"""V50 frozen multiscale research-only child-degree witness proposer.

Timeframe selection is fixed by structure, not outcomes: 15m parent / 5 = 3m
child. Every 3m strict width-one extremum must map uniquely to a strict 1m
width-three physical pivot. All 3m right-hand confirmation bars must close by
decision UTC. No pruning except deterministic replacement of consecutive
same-kind child pivots. No strategy, trade, quote, or P/L capability.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pandas as pd
from nested_elliott_v40 import ConfirmedPivot,EXPECTED,WIDTH,check_nested_structure
from propose_nested_v49 import _strict_minute_pivots

RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
PAPER_ELIGIBLE=False
ENTRY_SIGNAL=False
COMPLETE_RECURSIVE_CLASSIFIER=False
PARENT_MINUTES=15
CHILD_MINUTES=PARENT_MINUTES//5
COARSE_PIVOT_WIDTH=1

@dataclass(frozen=True)
class DegreeResult:
    source_bound_one_degree: bool
    reason: str
    eligible_coarse_pivots: int
    ambiguous_or_unverified_coarse_pivots: int
    per_leg_raw_counts: tuple[int,...]
    per_leg_selected_counts: tuple[int,...]
    entry_signal: bool=False
    paper_eligible: bool=False
    complete_recursive_elliott: bool=False

def _deny(reason, good=0, bad=0, raw=(), selected=()):
    return DegreeResult(False,str(reason),int(good),int(bad),tuple(raw),tuple(selected))

def propose_three_minute_child_degree(
    completed_1m:pd.DataFrame,
    parents:Sequence[ConfirmedPivot],
    *,
    decision_close_utc,
)->DegreeResult:
    if len(parents)!=9:
        return _deny("NINE_PARENTS_REQUIRED")
    if not isinstance(completed_1m,pd.DataFrame) or len(completed_1m)<50 or not {"timestamp","open","high","low","close"}.issubset(completed_1m.columns):
        return _deny("INVALID_MINUTE_SOURCE")
    try:
        dec=pd.Timestamp(decision_close_utc)
        if dec.tzinfo is None or dec.utcoffset() is None:
            return _deny("DECISION_NOT_UTC_AWARE")
        dec=dec.tz_convert("UTC")
        source=completed_1m.reset_index(drop=True)
        if any(pd.Timestamp(x).tzinfo is None or pd.Timestamp(x).utcoffset() is None for x in source["timestamp"]):
            return _deny("SOURCE_NOT_UTC_AWARE")
        times=pd.DatetimeIndex(pd.to_datetime(source["timestamp"],utc=True)).as_unit("ns")
        if times.hasnans or not times.is_unique or not times.is_monotonic_increasing:
            return _deny("SOURCE_CHRONOLOGY_FAILED")
        step=pd.Timedelta(minutes=1).value
        if np.any(np.diff(times.asi8)!=step) or np.any(times.asi8%step!=0):
            return _deny("SOURCE_NOT_CONTIGUOUS_1M")
        if times[-1]+pd.Timedelta(minutes=1)!=dec:
            return _deny("SOURCE_DECISION_NOT_EXACT_ASOF")
        if times[0].value % pd.Timedelta(minutes=CHILD_MINUTES).value!=0:
            return _deny("SOURCE_NOT_UTC_ALIGNED_FOR_3M")
        prices=source[["open","high","low","close"]].to_numpy(float)
        if not np.isfinite(prices).all() or np.any(prices<=0):
            return _deny("INVALID_SOURCE_PRICES")
        op,hi,lo,cl=prices.T
        if (hi<np.maximum.reduce([op,lo,cl])).any() or (lo>np.minimum.reduce([op,hi,cl])).any():
            return _deny("OHLC_BOUNDS_BROKEN")
    except Exception as exc:
        return _deny("SOURCE_PARSE_ERROR:"+str(exc))
    if any(not isinstance(p,ConfirmedPivot) or type(p.index)!=int or type(p.confirmed_at)!=int for p in parents):
        return _deny("PARENT_MALFORMED")
    if any(a.index>=b.index for a,b in zip(parents,parents[1:])):
        return _deny("PARENT_ORDER_FAILED")
    lower_pivots=_strict_minute_pivots(source)
    exact={(p.index,p.kind):p for p in lower_pivots}
    for p in parents:
        bound=exact.get((p.index,p.kind))
        if (bound is None or p.confirmed_at!=p.index+WIDTH or
            bound.price!=float(p.price) or p.confirmed_at>=len(source)-1):
            return _deny("PARENT_NOT_PAST_CONFIRMED_SOURCE_PIVOT")

    n_complete=len(source)//CHILD_MINUTES
    if n_complete<3:
        return _deny("INSUFFICIENT_COMPLETE_COARSE_BARS")
    grouped_hi=np.max(hi[:n_complete*CHILD_MINUTES].reshape(n_complete,CHILD_MINUTES),axis=1)
    grouped_lo=np.min(lo[:n_complete*CHILD_MINUTES].reshape(n_complete,CHILD_MINUTES),axis=1)
    good=[];bad=0
    for i in range(COARSE_PIVOT_WIDTH,n_complete-COARSE_PIVOT_WIDTH):
        # A 3m pivot is knowable only AFTER its right neighbor 3m candle closed.
        confirm_after=(i+COARSE_PIVOT_WIDTH+1)*CHILD_MINUTES
        if confirm_after>len(source):
            continue
        highpivot=grouped_hi[i]>grouped_hi[i-1] and grouped_hi[i]>grouped_hi[i+1]
        lowpivot=grouped_lo[i]<grouped_lo[i-1] and grouped_lo[i]<grouped_lo[i+1]
        if highpivot==lowpivot:
            if highpivot:bad+=1
            continue
        kind="high" if highpivot else "low"
        sliced=hi[i*CHILD_MINUTES:(i+1)*CHILD_MINUTES] if highpivot else lo[i*CHILD_MINUTES:(i+1)*CHILD_MINUTES]
        extreme=float(grouped_hi[i] if highpivot else grouped_lo[i])
        source_centers=np.flatnonzero(sliced==extreme)
        if len(source_centers)!=1:
            bad+=1
            continue
        center=i*CHILD_MINUTES+int(source_centers[0])
        x=exact.get((center,kind))
        if x is None or x.price!=extreme:
            bad+=1
            continue
        if times[confirm_after-1]+pd.Timedelta(minutes=1)>dec:
            return _deny("FUTURE_COARSE_CONFIRMATION",len(good),bad)
        good.append(x)
    rawcounts=[];selcounts=[];children=[]
    for legno,desired in enumerate(EXPECTED):
        start,end=parents[legno:legno+2]
        interior=[p for p in good if start.index<p.index<end.index]
        rawcounts.append(len(interior))
        chosen=[start]
        for pivot in interior:
            if pivot.kind==chosen[-1].kind:
                if len(chosen)==1:
                    return _deny(f"DEGREE_START_POLARITY_LEG_{legno}",len(good),bad,rawcounts,selcounts)
                old=chosen[-1]
                better=pivot.price>old.price if pivot.kind=="high" else pivot.price<old.price
                if better:chosen[-1]=pivot
            else:
                chosen.append(pivot)
        if chosen[-1].kind==end.kind:
            return _deny(f"DEGREE_END_POLARITY_LEG_{legno}",len(good),bad,rawcounts,selcounts)
        chosen.append(end)
        selcounts.append(len(chosen)-2)
        if len(chosen)!=desired+1:
            return _deny(f"DEGREE_COUNT_MISMATCH_LEG_{legno}:required_{desired-1}_interior_got_{len(chosen)-2}",
                         len(good),bad,rawcounts,selcounts)
        children.append(tuple(chosen))
    proof=check_nested_structure(source,parents,children,decision_close_utc=dec)
    if not proof.source_bound or not proof.one_child_degree_validated:
        return _deny("INDEPENDENT_V40_REJECTION:"+proof.reason,len(good),bad,rawcounts,selcounts)
    return DegreeResult(True,"BOUNDED_ONE_CHILD_DEGREE_3M_ORIGIN_V40_PASS",
                        len(good),bad,tuple(rawcounts),tuple(selcounts))
