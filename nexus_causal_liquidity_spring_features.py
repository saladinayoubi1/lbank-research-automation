"""Closed-candle causal spring-reclaim event helper; research only.

Strictly one predeclared 15m L0-H1-L2 support-sweep topology and stress
cost gate. This helper emits observational features only: no trading signal,
factory registration, portfolio writer, exchange requests or market replay.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from nexus_causal_liquidity_spring_review import (
    ConfirmedSpringPivot, review_spring_shape, RIGHT_BARS,
    MAX_CONFIRMATION_AGE,
)
from nexus_causal_macro_retest_features import stress_cost_screen

RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
MARKET_RUNS = 0
STEP_NS = 900_000_000_000

NUMERIC = (
    "spring_l0", "spring_h1", "spring_l2",
    "spring_l0_index", "spring_h1_index", "spring_l2_index",
    "spring_confirmed_at", "spring_sweep_depth_ratio",
    "spring_trigger_index", "spring_decision_range",
    "spring_flat_cost", "spring_target_net",
)
FLAGS = (
    "lagged_spring_active", "spring_first_support_reclaim_event",
    "spring_stress_cost_feasible", "spring_invalidated",
    "spring_expired", "spring_path_rejected", "spring_superseded",
)


def _validated(frame: pd.DataFrame, cutoff: pd.Timestamp) -> np.ndarray:
    if not {"timestamp","open","high","low","close"} <= set(frame.columns):
        raise ValueError("spring requires full completed 15m OHLC")
    ts = pd.to_datetime(frame["timestamp"],utc=True,errors="raise")
    if ts.isna().any() or any(pd.Timestamp(t).tzinfo is None
                              for t in frame["timestamp"]):
        raise ValueError("spring requires explicit aware candle CLOSE timestamps")
    if pd.Timestamp(cutoff).tzinfo is None:
        raise ValueError("last completed bar cutoff must be timezone-aware")
    ns=ts.to_numpy(dtype="datetime64[ns]").astype(np.int64)
    cut=pd.Timestamp(cutoff).tz_convert("UTC")
    if (len(ns)==0 or ts.duplicated().any() or not ts.is_monotonic_increasing
            or (len(ns)>1 and (np.diff(ns)!=STEP_NS).any())
            or (ns%STEP_NS!=0).any() or ts.iloc[-1]>cut):
        raise ValueError("spring needs unbroken completed UTC 15m grid")
    values=frame[["open","high","low","close"]].to_numpy(dtype=float)
    if (not np.isfinite(values).all() or (values<=0).any()
            or (values[:,1]<values.max(axis=1)).any()
            or (values[:,2]>values.min(axis=1)).any()):
        raise ValueError("spring invalid OHLC")
    return values


def _pivot(highs: np.ndarray,lows: np.ndarray,at: int) -> ConfirmedSpringPivot | None:
    if at<2*RIGHT_BARS:
        return None
    center=at-RIGHT_BARS
    left=center-RIGHT_BARS
    others_h=np.r_[highs[left:center],highs[center+1:at+1]]
    others_l=np.r_[lows[left:center],lows[center+1:at+1]]
    h=bool((highs[center]>others_h).all())
    l=bool((lows[center]<others_l).all())
    if h==l:return None
    return ConfirmedSpringPivot("high" if h else "low",center,at,
                                float(highs[center] if h else lows[center]))


def _path_error(
    p: tuple[ConfirmedSpringPivot,...],
    highs: np.ndarray,lows: np.ndarray,closes: np.ndarray,
    at: int,
) -> str | None:
    l0,h1,l2=p
    if lows[l0.index:h1.index+1].min() < float(l0.price):
        return "old_support_broken_before_H1"
    if highs[h1.index:l2.index+1].max() > float(h1.price):
        return "resistance_exceeded_before_L2"
    if lows[h1.index:l2.index+1].min() < float(l2.price):
        return "low_below_sweep_L2_inside_path"
    if lows[l2.index:at+1].min() < float(l2.price):
        return "sweep_L2_breached_before_confirmation"
    if (closes[l2.index+1:at+1] > float(l0.price)).any():
        return "support_reclaimed_before_L2_confirmation"
    return None


def build_closed_spring_features(
    closed_frame: pd.DataFrame, *, last_completed_at: pd.Timestamp,
    diagnostics: list[dict[str,Any]] | None = None,
) -> dict[str,pd.Series]:
    """Independent read-only feature observation on verified completed 15m OHLC.

    Pending setup is eligible from the candle strictly AFTER L2 right
    confirmation. Event identity is consumed on its first closed reclaim,
    even when any later cost/higher-frame gate would reject execution.
    """
    arr=_validated(closed_frame,last_completed_at)
    opens,highs,lows,closes=arr.T
    n=len(arr)
    lagged_range=pd.Series(highs-lows).shift(1).rolling(14,min_periods=14).mean().to_numpy()
    out={key:np.full(n,np.nan) for key in NUMERIC}
    out.update({key:np.zeros(n,dtype=bool) for key in FLAGS})
    pivots: list[ConfirmedSpringPivot]=[]
    pending: dict | None=None
    consumed:set[tuple[int,int]]=set()
    def emit(at:int,action:str,**values)->None:
        if diagnostics is not None:
            diagnostics.append(dict(decision_index=at,action=action,**values))

    for at in range(n):
        point=_pivot(highs,lows,at)
        accepted=False
        if point is not None:
            if pivots and pivots[-1].kind==point.kind:
                prev=pivots[-1]
                more=(point.price>prev.price) if point.kind=="high" else (point.price<prev.price)
                if more:
                    pivots[-1]=point
                    accepted=True
            else:
                pivots.append(point)
                pivots=pivots[-3:]
                accepted=True
        if accepted:
            emit(at,"pivot_accepted",kind=point.kind,
                 center_index=point.index,confirmed_at=point.confirmed_at)
            if pending is not None:
                out["spring_superseded"][at]=True
                emit(at,"setup_superseded",identity=list(pending["identity"]))
                pending=None
        if pending is not None:
            identity=pending["identity"]
            out["lagged_spring_active"][at]=True
            for k,value in (
                ("l0",pending["L0"]),("h1",pending["H1"]),("l2",pending["L2"]),
                ("l0_index",pending["L0_index"]),
                ("h1_index",pending["H1_index"]),
                ("l2_index",pending["L2_index"]),
                ("confirmed_at",pending["confirmed_at"]),
                ("sweep_depth_ratio",pending["sweep_depth_ratio"]),
            ):
                out["spring_"+k][at]=float(value)
            if lows[at]<float(pending["L2"]) or highs[at]>float(pending["H1"]):
                out["spring_invalidated"][at]=True
                emit(at,"invalidated",identity=list(identity),
                     reason="L2_support_breach_or_H1_resistance_overshoot")
                pending=None
            elif at-pending["confirmed_at"]>MAX_CONFIRMATION_AGE:
                out["spring_expired"][at]=True
                emit(at,"expired",identity=list(identity))
                pending=None
            elif closes[at-1]<=float(pending["L0"])<closes[at]:
                consumed.add(identity)
                out["spring_first_support_reclaim_event"][at]=True
                out["spring_trigger_index"][at]=at
                atr=float(lagged_range[at])
                screen=stress_cost_screen(float(closes[at]),atr,
                                          float(pending["cost_span"]))
                out["spring_decision_range"][at]=atr
                out["spring_stress_cost_feasible"][at]=bool(screen["feasible"])
                out["spring_flat_cost"][at]=screen.get("flat_cost",np.nan)
                out["spring_target_net"][at]=screen.get("target_net",np.nan)
                emit(at,"first_support_reclaim_consumed",
                     identity=list(identity),cost_screen=screen)
                pending=None
        if not accepted or point.kind!="low" or len(pivots)!=3:
            continue
        geometry=review_spring_shape(pivots,at+1)
        if geometry is None:continue
        identity=geometry["identity"]
        if identity in consumed:
            emit(at,"identity_already_consumed",identity=list(identity))
            continue
        reason=_path_error(tuple(pivots),highs,lows,closes,at)
        if reason is not None:
            out["spring_path_rejected"][at]=True
            emit(at,"path_rejected",identity=list(identity),reason=reason)
            continue
        pending=geometry
        emit(at,"setup_stored_for_next_bar",identity=list(identity),
             earliest_decision_index=at+1)
    return {key:pd.Series(value,index=closed_frame.index) for key,value in out.items()}
