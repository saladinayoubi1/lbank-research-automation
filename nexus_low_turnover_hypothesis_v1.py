"""Preregistered causal 4h low-turnover target generator: research only.

No candidate selection, holdout reading, Paper admission or exchange access.
Signals from completed candles execute only through a separate next-open engine.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

SCHEMA = "nexus.low-turnover-hypothesis-prereg.v1"
EXPECTED_MANIFEST: dict[str, Any] = {
    "schema_version": SCHEMA,
    "experiment_id": "nexus-bybit-btc-eth-4h-low-turnover-research-v1",
    "market": "bybit_public_spot_research_only",
    "symbols": ["BTCUSDT", "ETHUSDT"],
    "timeframe": "hour4",
    "variants": [
        {"lookback": 20, "entry_deadband": 0.01, "min_hold_bars": 6, "exit_cooldown_bars": 3},
        {"lookback": 40, "entry_deadband": 0.015, "min_hold_bars": 6, "exit_cooldown_bars": 3},
    ],
    "execution": {
        "conservative": {"fee_bps": 10.0, "slippage_bps": 5.0},
        "stress": {"fee_bps": 25.0, "slippage_bps": 15.0},
    },
    "evaluation": {
        "historical_development_training_only": True,
        "previously_inspected_locked_holdout_is_pristine": False,
        "future_holdout_no_earlier_than_utc": "2026-09-26T00:00:00Z",
        "future_holdout_must_follow_exact_code_freeze": True,
        "future_holdout_used_for_selection": False,
        "minimum_new_forward_fills_per_profile": 4,
        "forward_activity_requires_separate_review": True,
    },
    "authority": {
        "research_only": True, "paper_only": True,
        "live_trading_authority": False, "private_credentials_allowed": False,
        "automatic_strategy_promotion": False, "automatic_paper_forward_started": False,
    },
}


class LowTurnoverHypothesisError(ValueError):
    pass


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def load_manifest(path: str | Path) -> dict[str, Any]:
    try:
        candidate = json.loads(Path(path).read_text(encoding="utf-8"))
        if _canonical(candidate) != _canonical(EXPECTED_MANIFEST):
            raise LowTurnoverHypothesisError("preregistered manifest changed")
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise LowTurnoverHypothesisError("preregistered manifest is unavailable or invalid") from exc
    return candidate


def generate_targets(frame: pd.DataFrame, config: Mapping[str, Any]) -> pd.Series:
    """Completed-close signals; next-open execution belongs to the shared simulator."""
    allowed = {_canonical(row) for row in EXPECTED_MANIFEST["variants"]}
    try:
        requested = _canonical(dict(config))
    except (TypeError, ValueError) as exc:
        raise LowTurnoverHypothesisError("invalid strategy configuration") from exc
    if requested not in allowed:
        raise LowTurnoverHypothesisError("unregistered configuration")
    if not isinstance(frame, pd.DataFrame) or not {"timestamp", "close"} <= set(frame.columns):
        raise LowTurnoverHypothesisError("four-hour closed-candle frame is missing")
    lookback = int(config["lookback"])
    if len(frame) < lookback + 7:
        raise LowTurnoverHypothesisError("insufficient closed-candle training history")
    try:
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        prices = pd.to_numeric(frame["close"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise LowTurnoverHypothesisError("unparseable timestamp or close") from exc
    if (timestamps.isna().any() or not timestamps.is_monotonic_increasing
            or timestamps.duplicated().any()
            or not (timestamps.diff().iloc[1:] == pd.Timedelta(hours=4)).all()
            or any(not math.isfinite(p) or p <= 0 for p in prices)):
        raise LowTurnoverHypothesisError("invalid or noncausal four-hour closed-candle frame")
    held = False
    entry_index: int | None = None
    last_exit_index: int | None = None
    values: list[float] = []
    for i in range(len(prices)):
        change = float(prices.iloc[i] / prices.iloc[i - lookback] - 1.0) if i >= lookback else None
        if (not held and change is not None and change > config["entry_deadband"]
                and (last_exit_index is None or i - last_exit_index > config["exit_cooldown_bars"])):
            held = True
            entry_index = i
        elif (held and change is not None and change <= 0.0
              and entry_index is not None and i - entry_index >= config["min_hold_bars"]):
            held = False
            last_exit_index = i
            entry_index = None
        values.append(float(held))
    return pd.Series(values, index=frame.index, dtype="float64")
