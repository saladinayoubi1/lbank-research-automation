"""Spring v12 research observer backed by unchanged, source-pinned v11 observer.

The existing observer does not expose a Spring profile. Project a COPY into
its already-tested ABC event/active/cost-span interface, observe the SAME
frozen backtest function, then replace every temporary ABC setup label with
the original Spring geometry from its source row. The adapter is explicit
in evidence; the shared source and existing traces are never rewritten.
"""
from __future__ import annotations

from copy import deepcopy
import math

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as engine
from nexus_backtest_observer import observe_backtest
from nexus_spring_research_signal import research_signals, candidate_config

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
BRIDGE_PROFILE = "abc_correction"
SPRING_PROFILE = "liquidity_spring"
ALIAS = {
    "abc_first_close_break_event":"spring_first_support_reclaim_event",
    "lagged_abc_active":"lagged_spring_active",
    "abc_stress_cost_feasible":"spring_stress_cost_feasible",
    "lagged_abc_h0":"spring_h1",
    "lagged_abc_lc":"spring_l2",
}
SETUP_FIELDS = (
    "spring_l0","spring_h1","spring_l2","spring_l0_index",
    "spring_h1_index","spring_l2_index","spring_confirmed_at",
    "spring_sweep_depth_ratio","spring_trigger_index",
    "spring_decision_range","spring_flat_cost","spring_target_net",
)
VALID_PROFILES = {(10.,5.),(25.,15.)}


def _setup(row: pd.Series) -> dict[str,float|None]:
    values={}
    for key in SETUP_FIELDS:
        if key not in row:raise ValueError("Missing Spring observation setup "+key)
        value=float(row[key])
        values[key]=value if math.isfinite(value) else None
    return values


def observe_spring_candidate(
    frame: pd.DataFrame, *, fee_bps: float, slip_bps: float,
    index_offset: int = 0,
) -> dict:
    """Record real engine decisions/fills on synthetic or separately frozen research only."""
    if (fee_bps,slip_bps) not in VALID_PROFILES:
        raise ValueError("Spring cost pair not preregistered")
    if type(index_offset) is not int or index_offset < 0:
        raise ValueError("Spring index offset must be a nonnegative integer")
    if frame.empty:
        raise ValueError("No Spring research bars")
    if not set(ALIAS.values()).issubset(frame.columns):
        raise ValueError("Missing Spring event or structural observer inputs")
    if set(ALIAS).intersection(frame.columns):
        raise ValueError("Legacy ABC observer namespace collision")
    event=np.flatnonzero(frame["spring_first_support_reclaim_event"].to_numpy()==1)
    for i in event:
        global_i=i+index_offset
        row=frame.iloc[i]
        setup=_setup(row)
        if (not all(setup[k] is not None for k in SETUP_FIELDS)
              or not (setup["spring_h1"]>setup["spring_l0"]>setup["spring_l2"]>0)
              or not (setup["spring_l0_index"]<setup["spring_h1_index"]<
                      setup["spring_l2_index"])
              or int(setup["spring_trigger_index"])!=global_i
              or not (setup["spring_confirmed_at"]<global_i and
                      setup["spring_confirmed_at"]==
                      setup["spring_l2_index"]+3)
              or not (1<=global_i-setup["spring_confirmed_at"]<=16)
              or not (0<setup["spring_sweep_depth_ratio"]<=0.382)
              or not (float(row["low"])>=setup["spring_l2"]
                      and float(row["high"])<=setup["spring_h1"])
              or not (float(row["previous_close"])<=setup["spring_l0"]<
                      float(row["close"]))):
            raise ValueError("Spring observation event violates sealed causal geometry")
    signals=research_signals(frame)
    projected=frame.copy(deep=True)
    for old,new in ALIAS.items():
        projected[old]=frame[new].copy()
    observed=observe_backtest(
        engine.backtest,projected,signals,fee_bps=fee_bps,
        slip_bps=slip_bps,risk_variant=0,index_offset=index_offset,
        event_profile=BRIDGE_PROFILE,
    )
    def rewrite(decision:dict):
        i=decision["bar_index"]-index_offset
        if i<0 or i>=len(frame):
            raise ValueError("Spring observer decision outside source partition")
        return {**decision,"setup":_setup(frame.iloc[i])}
    for event_record in observed["price_events"]:
        event_record["setup"]=_setup(frame.iloc[event_record["bar_index"]-index_offset])
        event_record["denial_fields"]=[
            ALIAS.get(name,name) for name in event_record["denial_fields"]
        ]
    for trade in observed["trades"]:
        trade["decision"]=rewrite(trade["decision"])
    for attempt in observed["entry_attempts"]:
        if attempt["decision"] is not None:
            attempt["decision"]=rewrite(attempt["decision"])
    if observed["unfilled_pending_decision"] is not None:
        observed["unfilled_pending_decision"]=rewrite(observed["unfilled_pending_decision"])
    observed.update(
        mechanism=candidate_config()["mechanism"],
        observation_event_profile=SPRING_PROFILE,
        original_frozen_observer_profile=BRIDGE_PROFILE,
        disclosure="Read-only Spring namespace projected onto source-bound ABC observer copy; backtest AST unchanged.",
        research_only=True,live_enabled=False,auto_demo=False,
    )
    return observed
