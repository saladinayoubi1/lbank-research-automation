"""Append-only, non-executing parent-frame integration for v12 spring research.

This is feature inspection, not a trading strategy adapter or signal scheduler.
No changes to shared engine, order writer, factory, execution or market loader.
"""
from __future__ import annotations

from copy import deepcopy

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as parent
from nexus_causal_liquidity_spring_features import build_closed_spring_features
from nexus_causal_macro_retest_features import stress_cost_screen

RESEARCH_ONLY = True
LIVE_ENABLED = False
DEMO_ENABLED = False
FACTORY_REGISTERED = False
ORDERS_ENABLED = False


def inspect_parent_with_spring(
    frames: dict[str, pd.DataFrame],
    *, diagnostics: list[dict] | None = None,
) -> pd.DataFrame:
    """Read-only spring features on unmodified, causally closed parent OHLC.

    The interface intentionally provides no candidate signal or backtest.
    """
    parent_frame=parent.build_features(deepcopy(frames))
    if parent_frame.empty:
        raise ValueError("no complete closed candles")
    if not {"decision_at","timestamp","open","high","low","close","atr",
            "previous_close","h4_up","h1_vol_ok"} <= set(parent_frame.columns):
        raise ValueError("missing original closed parent feature contract")
    closed=parent_frame[["open","high","low","close"]].copy()
    closed["timestamp"]=parent_frame["decision_at"]
    spring=build_closed_spring_features(
        closed,last_completed_at=parent_frame["decision_at"].iloc[-1],
        diagnostics=diagnostics,
    )
    if set(spring) & set(parent_frame.columns):
        raise ValueError("spring namespace collides with frozen parent")
    new=pd.DataFrame(spring,index=parent_frame.index)
    event=new["spring_first_support_reclaim_event"].to_numpy(dtype=bool)
    if event.any():
        left=new.loc[event,"spring_decision_range"].to_numpy(dtype=float)
        right=parent_frame.loc[event,"atr"].to_numpy(dtype=float)
        if not (np.isfinite(right).all() and
                np.allclose(left,right,atol=1e-10,rtol=1e-12)):
            raise ValueError("independent lagged range disagrees with parent ATR")
        for i in np.flatnonzero(event):
            row=parent_frame.iloc[i]
            p=new.iloc[i]
            screen=stress_cost_screen(
                float(row["close"]),float(row["atr"]),
                float(p["spring_h1"]-p["spring_l2"]),
            )
            if (bool(p["spring_stress_cost_feasible"])!=bool(screen["feasible"])
                    or not np.isclose(float(p["spring_flat_cost"]),float(screen["flat_cost"]))):
                raise ValueError("spring stress cost not parent-compatible")
    return pd.concat([parent_frame,new],axis=1)
