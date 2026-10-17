"""V49 deterministic research-only lower-degree witness proposer for V40.

No selection by P/L, threshold fitting, arbitrary pivot skipping, post-decision
evidence or signals. The frozen degree rule is: exactly all alternating strict
width-3 minute extrema of each parent leg (more extreme same-kind internal
replacement only). Fail closed when this single predeclared segmentation does
not match V40 5-3-5-3-5 + 5-3-5 cardinality.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Sequence
import numpy as np
import pandas as pd

from nested_elliott_v40 import (
    ConfirmedPivot, EXPECTED, WIDTH, check_nested_structure,
)

RESEARCH_ONLY=True
LIVE_ENABLED=False
AUTO_DEMO=False
ENTRY_SIGNAL=False
PAPER_ELIGIBLE=False
PARAMETER_TUNING=False

@dataclass(frozen=True)
class WitnessProposal:
    accepted: bool
    reason: str
    raw_child_extrema_per_leg: tuple[int,...]
    selected_child_extrema_per_leg: tuple[int,...]
    validated_bounded_one_degree: bool
    entry_signal: bool=False
    paper_eligible: bool=False
    recursively_complete: bool=False

def _fail(reason:str, raw=(), chosen=()):
    return WitnessProposal(False,reason,tuple(raw),tuple(chosen),False)

def _strict_minute_pivots(closed_1m:pd.DataFrame):
    """Only strict unique low XOR high; center+WIDTH confirmed before decision."""
    h=closed_1m["high"].to_numpy(dtype=float)
    l=closed_1m["low"].to_numpy(dtype=float)
    n=len(h)
    pivots=[]
    for center in range(WIDTH,n-WIDTH-1):
        neighbors=[k for k in range(center-WIDTH,center+WIDTH+1) if k!=center]
        is_hi=all(h[center]>h[k] for k in neighbors)
        is_lo=all(l[center]<l[k] for k in neighbors)
        if is_hi==is_lo:continue
        kind="high" if is_hi else "low"
        pivots.append(ConfirmedPivot(kind,int(center),int(center+WIDTH),
                                     float(h[center] if is_hi else l[center])))
    return pivots

def propose_children_fixed(
    closed_1m:pd.DataFrame,
    parents:Sequence[ConfirmedPivot],
    *,
    decision_close_utc:object,
)->WitnessProposal:
    """Single non-adjustable proposed partition; never emits a trading signal.

    Caller must pin/verify source parquet via the V42 as-of gate. For every
    ACCEPTED witness, the independent V40 full input and source validator is
    always invoked. Rejected proposals cannot become signals.
    """
    if len(parents)!=9:
        return _fail("NINE_PARENT_ANCHORS_REQUIRED")
    if not isinstance(closed_1m,pd.DataFrame) or not all(
      c in closed_1m for c in ("timestamp","open","high","low","close")
    ):
        return _fail("INVALID_1M_SOURCE")
    try:
        stamp=pd.Timestamp(decision_close_utc)
        ts=pd.DatetimeIndex(pd.to_datetime(closed_1m["timestamp"],utc=True))
        if stamp.tzinfo is None or stamp.utcoffset() is None or len(ts)<15:
            return _fail("INVALID_DECISION")
        stamp=stamp.tz_convert("UTC")
        if ts[-1]+pd.Timedelta(minutes=1)!=stamp or ts.hasnans or not ts.is_unique:
            return _fail("INCOMPLETE_OR_FUTURE_SOURCE")
        values=closed_1m[["open","high","low","close"]].to_numpy(float)
        if not np.isfinite(values).all() or (values<=0).any():
            return _fail("INVALID_OHLC")
        if (values[:,1]<values[:,[0,2,3]].max(axis=1)).any() or (values[:,2]>values[:,[0,1,3]].min(axis=1)).any():
            return _fail("INVALID_OHLC_BOUNDS")
        if (np.diff(ts.asi8)!=pd.Timedelta(minutes=1).value).any() or (ts.asi8%pd.Timedelta(minutes=1).value).any():
            return _fail("MISSING_OR_OFFGRID_SOURCE")
    except Exception:
        return _fail("INVALID_DECISION_OR_SOURCE")
    if any(not isinstance(p,ConfirmedPivot) or type(p.index)!=int or
           type(p.confirmed_at)!=int for p in parents):
        return _fail("PARENT_EVIDENCE_MALFORMED")
    if any(b.index<=a.index for a,b in zip(parents,parents[1:])):
        return _fail("PARENT_CHRONOLOGY")
    if any(p.confirmed_at!=p.index+WIDTH or p.confirmed_at>=len(ts)-1 for p in parents):
        return _fail("PARENT_CONFIRMATION_IN_FUTURE")
    raw=_strict_minute_pivots(closed_1m)
    at_index={(p.index,p.kind):p for p in raw}
    for p in parents:
        recorded=at_index.get((p.index,p.kind))
        if recorded is None or recorded.price!=float(p.price):
            return _fail("PARENT_NOT_STRICT_SOURCE_BOUND")
    buckets=[];raw_counts=[];chosen_counts=[]
    for leg_idx,desired in enumerate(EXPECTED):
        left,right=parents[leg_idx:leg_idx+2]
        interior=[p for p in raw if left.index<p.index<right.index]
        raw_counts.append(len(interior))
        selected=[left]
        for point in interior:
            if point.kind==selected[-1].kind:
                if len(selected)==1:
                    return _fail(f"ANCHOR_NOT_VALID_SEGMENT_START_{leg_idx}",raw_counts,chosen_counts)
                prev=selected[-1]
                more=(point.price>prev.price if point.kind=="high" else point.price<prev.price)
                if more:selected[-1]=point
            else:
                selected.append(point)
        if selected[-1].kind==right.kind:
            return _fail(f"ANCHOR_NOT_VALID_SEGMENT_END_{leg_idx}",raw_counts,chosen_counts)
        selected.append(right)
        chosen_counts.append(len(selected)-2)
        if len(selected)!=desired+1:
            return _fail(f"CHILD_COUNT_MISMATCH_LEG_{leg_idx}:expected_{desired-1}_interior_observed_{len(selected)-2}",
                raw_counts,chosen_counts)
        buckets.append(tuple(selected))
    proof=check_nested_structure(closed_1m,parents,buckets,decision_close_utc=stamp)
    if not proof.source_bound or not proof.one_child_degree_validated:
        return _fail("V40_REJECTED:"+proof.reason,raw_counts,chosen_counts)
    return WitnessProposal(True,"BOUNDED_ONE_CHILD_DEGREE_SOURCE_PROOF_ONLY",
           tuple(raw_counts),tuple(chosen_counts),True)
