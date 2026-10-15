"""One explicit, preregistered research candidate using the unchanged engine.

No automatic factory registration, Paper consumer, market IO or order API.
Archive frames have OPEN timestamps; the five-swing helper requires CLOSE.
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
from nexus_causal_elliott_five_swing_features import build_lagged_elliott_five_swing_features

RESEARCH_ONLY = True
LIVE_ENABLED = False
FACTORY_REGISTERED = False
ROOT = Path(__file__).resolve().parent
PREREGISTRATION = ROOT / "research" / "elliott_five_swing_candidate_preregistration.json"
PARAMETERS = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
EXPECTED_PREREGISTRATION_DIGEST = "ede171e4dc320d72b32e8b8241d0a468c3a85ebdb1e410617b72a5734eabe6ec"
if (engine.digest({k: v for k, v in PARAMETERS.items() if k != "preregistration_digest"})
        != PARAMETERS.get("preregistration_digest")
        or PARAMETERS["preregistration_digest"] != EXPECTED_PREREGISTRATION_DIGEST):
    raise ValueError("Frozen Elliott five-swing candidate preregistration differs")
for _name, _expected in PARAMETERS["feature_sha256"].items():
    if hashlib.sha256((ROOT / _name).read_bytes()).hexdigest() != _expected:
        raise ValueError("Frozen Elliott candidate source differs: " + _name)
if engine.digest(PARAMETERS["conditions"]) != PARAMETERS["candidate_config"]["contract_digest"]:
    raise ValueError("Frozen Elliott candidate conditions differ")


def candidate_config() -> dict:
    return deepcopy(PARAMETERS["candidate_config"])


def build_elliott_research_features(
    frames: dict[str, pd.DataFrame], *, diagnostics: list[dict] | None = None,
) -> pd.DataFrame:
    """Reuse every parent feature unchanged; append only new Elliott columns.

The parent validates raw UTC15m/1h/4h OHLCV and derives CLOSED availability.
Copy that decision_at to the helper's close timestamp, exactly once. This is
an isolated research adapter, not an installed Paper engine replacement.
"""
    result = engine.build_features(deepcopy(frames))
    closed = result[["open", "high", "low", "close"]].copy()
    closed["timestamp"] = result["decision_at"]
    added = build_lagged_elliott_five_swing_features(closed, diagnostics=diagnostics)
    if set(added) & set(result.columns):
        raise ValueError("Elliott candidate feature collision")
    return pd.concat([result, pd.DataFrame(added, index=result.index)], axis=1)


def candidate_signal_for(frame: pd.DataFrame, config: dict | None = None) -> np.ndarray:
    """Fixed context/body/fresh-event/cost/ATR gates, no parameter search."""
    if config is not None and engine.digest(config) != PARAMETERS["candidate_config_fingerprint"]:
        raise ValueError("Unreviewed Elliott candidate configuration")
    required = {"open", "high", "low", "close", "previous_close", "atr", "h4_up", "h1_vol_ok",
                "lagged_elliott5_active", "elliott5_close_breakout_event", "elliott5_cost_feasible"}
    if not required.issubset(frame.columns):
        raise ValueError("Elliott candidate missing required signal fields")
    values = frame[["open", "high", "low", "close", "previous_close", "atr"]].to_numpy(dtype=float)
    finite = np.isfinite(values).all(axis=1) & (values > 0).all(axis=1)
    signal = (frame["h4_up"].eq(1) & frame["h1_vol_ok"].eq(1)
              & frame["lagged_elliott5_active"].eq(1)
              & frame["elliott5_close_breakout_event"].eq(1)
              & frame["elliott5_cost_feasible"].eq(1)
              & frame["close"].gt(frame["open"])
              & frame["close"].gt(frame["previous_close"]))
    return signal.fillna(False).to_numpy(dtype=bool) & finite


def backtest_elliott_candidate(
    frame: pd.DataFrame, *, fee_bps: float, slip_bps: float, index_offset: int = 0,
) -> dict:
    """Actual unchanged next-open fills with explicit Elliott identity trace.

Only the two frozen simulation profiles are supported. Passing synthetic
numeric tests is not market qualification or owner trading admission.
"""
    profiles = PARAMETERS["costs_per_leg_bps"].values()
    if (fee_bps, slip_bps) not in {(p["fee"], p["slippage"]) for p in profiles}:
        raise ValueError("Unreviewed Elliott simulation cost profile")
    return observe_backtest(engine.backtest, frame, candidate_signal_for(frame),
                            fee_bps=fee_bps, slip_bps=slip_bps, risk_variant=0,
                            index_offset=index_offset, event_profile="elliott_five_swing")
