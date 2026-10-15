"""Frozen one-configuration research adapter for causal ABC corrective proxy.

Unchanged parent features/backtest and source-bound execution observer.
Never registers in Strategy Finder, changes Paper state or sends live orders.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

import nexus_composite_strategy_research as engine
from nexus_backtest_observer import observe_backtest
from nexus_causal_abc_corrective_features import build_closed_abc_features

RESEARCH_ONLY = True
LIVE_ENABLED = False
FACTORY_REGISTERED = False
AUTO_DEMO = False

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "research" / "causal_abc_corrective_reclaim_v11_preregistration.json"
EXPECTED_PREREG_SHA256 = "dfcfc9b0d4f46acddb3ee047f78368b7f349d785f7836ec3f9c598eee1e7cbcb"
if hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest() != EXPECTED_PREREG_SHA256:
    raise ValueError("ABC preregistration source differs from sealed v11 design")
PARAMETERS = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
if (PARAMETERS["proposed_mechanism_id"] != "research_causal_abc_corrective_reclaim"
        or PARAMETERS["hypothesis_count"] != 1
        or PARAMETERS["parameter_configurations"] != 1
        or PARAMETERS["authority"]["research_only"] is not True
        or PARAMETERS["authority"]["live_enabled"] is not False
        or PARAMETERS["authority"]["auto_demo_promotion"] is not False):
    raise ValueError("ABC preregistration authority or identity mismatch")

_CANDIDATE = {
    "mechanism": "research_causal_abc_corrective_reclaim",
    "risk_variant": 0,
    "entry_model": "closed_4h_1h_15m_next_open",
    "type": "ABC_like_H_L_H_L_closed_pivot_breakout_research",
}
_ALLOWED_COSTS = frozenset(
    (float(x["fee"]),float(x["slippage"]))
    for x in (PARAMETERS["cost_protection"]["conservative_per_leg_bps"],
              PARAMETERS["cost_protection"]["stress_per_leg_bps"])
)


def candidate_config() -> dict:
    return deepcopy(_CANDIDATE)


def build_abc_research_features(
    frames: dict[str, pd.DataFrame], *,
    diagnostics: list[dict] | None = None,
) -> pd.DataFrame:
    """Only append ABC helper output to a copy of verified original feature frame."""
    result = engine.build_features(deepcopy(frames))
    closed = result[["open", "high", "low", "close"]].copy()
    closed["timestamp"] = result["decision_at"]
    added = build_closed_abc_features(
        closed,last_completed_at=result["decision_at"].iloc[-1],
        diagnostics=diagnostics,
    )
    if set(added).intersection(result.columns):
        raise ValueError("ABC candidate feature namespace collision")
    return pd.concat([result, pd.DataFrame(added, index=result.index)], axis=1)


def candidate_signal_for(frame: pd.DataFrame, config: dict | None = None) -> np.ndarray:
    """Single fixed context/body/event/cost gate, no searching or altered config."""
    if config is not None and config != _CANDIDATE:
        raise ValueError("Unregistered ABC candidate configuration")
    fields={"open","high","low","close","previous_close","atr","h4_up","h1_vol_ok",
            "lagged_abc_active","abc_first_close_break_event","abc_stress_cost_feasible"}
    if not fields.issubset(frame.columns):
        raise ValueError("ABC candidate missing mandatory input features")
    numeric=frame[["open","high","low","close","previous_close","atr"]].to_numpy(dtype=float)
    finite=np.isfinite(numeric).all(axis=1) & (numeric > 0).all(axis=1)
    valid=(frame["h4_up"].eq(1) & frame["h1_vol_ok"].eq(1)
           & frame["lagged_abc_active"].eq(1)
           & frame["abc_first_close_break_event"].eq(1)
           & frame["abc_stress_cost_feasible"].eq(1)
           & frame["close"].gt(frame["open"])
           & frame["close"].gt(frame["previous_close"]))
    return valid.fillna(False).to_numpy(dtype=bool) & finite


def backtest_abc_candidate(
    frame: pd.DataFrame, *, fee_bps: float, slip_bps: float,
    index_offset: int = 0,
) -> dict:
    """Exact original engine, verified observer, two fixed profiles only.

    Permits synthetic and separate future frozen-market research evaluation.
    By itself this does not constitute an approved archive market replay.
    """
    if (fee_bps,slip_bps) not in _ALLOWED_COSTS:
        raise ValueError("ABC candidate cost profile not registered")
    if type(index_offset) is not int or index_offset < 0:
        raise ValueError("ABC candidate index_offset invalid")
    return observe_backtest(
        engine.backtest,frame,candidate_signal_for(frame),
        fee_bps=fee_bps,slip_bps=slip_bps,risk_variant=0,
        index_offset=index_offset,event_profile="abc_correction",
    )
