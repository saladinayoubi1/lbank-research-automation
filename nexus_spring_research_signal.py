"""Fixed, preregistered Spring v12 research-only signal screening.

The output is an in-memory boolean research mask, NOT an order or a
backtest; changing the shared execution engine is expressly prohibited.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

from nexus_spring_parent_feature_review import inspect_parent_with_spring

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
ORDER_EXECUTION_ENABLED = False

PREREG = Path(__file__).resolve().parent / "research" / "causal_liquidity_spring_reclaim_v12_preregistration.json"
PREREG_SHA256 = "5a4daad7a0821a1c43468699ecac4508cc720d18cba5695dfbb8858461029aa6"
canonical = PREREG.read_bytes().replace(b"\r\n", b"\n")
if hashlib.sha256(canonical).hexdigest() != PREREG_SHA256:
    raise ValueError("Spring v12 preregistration source changed")
SPEC = json.loads(canonical.decode("utf-8"))
if not (SPEC["mechanism_id"] == "research_causal_liquidity_spring_reclaim_v12"
        and SPEC["hypothesis_count"] == SPEC["parameter_configurations"] == 1
        and SPEC["architecture"]["research_only"] is True
        and SPEC["architecture"]["live_trading_enabled"] is False
        and SPEC["architecture"]["automatic_demo_promotion"] is False):
    raise ValueError("Spring v12 configuration is not approved")

CONFIG = {
    "mechanism": SPEC["mechanism_id"],
    "risk_variant": 0,
    "entry_model": "closed_4h_1h_15m_next_open",
    "type": "preregistered_three_pivot_support_sweep_reclaim",
}


def candidate_config() -> dict:
    return deepcopy(CONFIG)


def research_signals(frame: pd.DataFrame, config: dict | None = None) -> np.ndarray:
    """Only the fixed h4/h1/body/reclaim/stress-cost intersection is admitted."""
    if config is not None and config != CONFIG:
        raise ValueError("Spring v12 does not permit alternative configurations")
    required = {"open", "high", "low", "close", "previous_close", "atr",
                "h4_up", "h1_vol_ok", "lagged_spring_active",
                "spring_first_support_reclaim_event", "spring_stress_cost_feasible"}
    if not required.issubset(frame.columns):
        raise ValueError("Spring v12 missing mandatory causal features")
    prices = frame[["open", "high", "low", "close", "previous_close", "atr"]].to_numpy(dtype=float)
    finite = np.isfinite(prices).all(axis=1) & (prices > 0).all(axis=1)
    valid = (frame["h4_up"].eq(1) & frame["h1_vol_ok"].eq(1)
             & frame["lagged_spring_active"].eq(1)
             & frame["spring_first_support_reclaim_event"].eq(1)
             & frame["spring_stress_cost_feasible"].eq(1)
             & frame["close"].gt(frame["open"])
             & frame["close"].gt(frame["previous_close"]))
    return valid.fillna(False).to_numpy(dtype=bool) & finite


def inspect_research_signals(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, np.ndarray]:
    """Attach source-bound Spring features; do not schedule any fills."""
    frame = inspect_parent_with_spring(frames)
    return frame, research_signals(frame)
