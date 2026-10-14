"""One frozen Elliott-inspired early-wave setup; only closed-bar observations.

The proposed wave-two low j is known at close j+3. A stored setup can be used
only on a later closed bar, never at that pivot or its confirmation close.
Current closed-bar events use the previous bar's setup; newly confirmed pivots
change only future state. This does not verify a complete Elliott wave count.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
import hashlib
import json

import numpy as np
import pandas as pd

PREREGISTRATION = Path(__file__).resolve().parent / "research" / "causal_elliott_wave12_v9_preregistration.json"
PARAMETERS = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
_unsigned = {k: v for k, v in PARAMETERS.items() if k != "preregistration_digest"}
_digest = hashlib.sha256(json.dumps(_unsigned, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False).encode()).hexdigest()
if _digest != PARAMETERS.get("preregistration_digest") or _digest != "2845fbc71ce1c5ee5ee986a7206bd19a05776fd6185d5f914475f35f57638301":
    raise ValueError("Frozen Elliott wave12 preregistration differs")

WIDTH = 3
MAX_SPAN = 192
MAX_ELIGIBLE_AGE = 32
RETRACEMENT = (0.382, 0.786)
ROUNDOFF = 1e-12  # representation only, never an economic tuning parameter


@dataclass(frozen=True)
class ElliottPivot:
    kind: str
    index: int
    confirmed_at: int
    price: float


def elliott_wave12_geometry(pivots: Sequence[ElliottPivot]) -> dict[str, float] | None:
    """Three-pivot proposed wave12 geometry; no future-wave classification."""
    if len(pivots) != 3 or tuple(p.kind for p in pivots) != ("low", "high", "low"):
        return None
    if any(b.index <= a.index for a, b in zip(pivots, pivots[1:])):
        return None
    if any(p.index < 0 or p.confirmed_at != p.index + WIDTH for p in pivots):
        return None
    if pivots[-1].index - pivots[0].index > MAX_SPAN:
        return None
    prices = np.asarray([p.price for p in pivots], dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        return None
    origin, high, correction = map(float, prices)
    if not origin < correction < high:
        return None
    retracement = (high - correction) / (high - origin)
    if not RETRACEMENT[0] - ROUNDOFF <= retracement <= RETRACEMENT[1] + ROUNDOFF:
        return None
    return {"origin_price": origin, "wave1_high": high, "wave2_low": correction,
            "retracement": retracement}


def _confirmed_pivot(highs: np.ndarray, lows: np.ndarray, at: int) -> ElliottPivot | None:
    if at < WIDTH * 2:
        return None
    center = at - WIDTH
    start, stop = center - WIDTH, at + 1
    other_highs = np.concatenate((highs[start:center], highs[center + 1:stop]))
    other_lows = np.concatenate((lows[start:center], lows[center + 1:stop]))
    is_high = bool((highs[center] > other_highs).all())
    is_low = bool((lows[center] < other_lows).all())
    if is_high == is_low:  # tied extrema or unknown intrabar high/low order
        return None
    kind, price = ("high", highs[center]) if is_high else ("low", lows[center])
    return ElliottPivot(kind, center, at, float(price))


def build_lagged_elliott_wave12_features(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Evaluate lagged setup, current closed price event, then future pivot state."""
    if not {"timestamp", "open", "high", "low", "close"}.issubset(frame.columns):
        raise ValueError("Elliott wave12 input missing timestamp/OHLC")
    times = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if (times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing
            or not (times.diff().dropna() == pd.Timedelta(minutes=15)).all()
            or any(t.value % 900_000_000_000 for t in times)):
        raise ValueError("Elliott wave12 requires a complete aligned UTC15m grid")
    prices = frame[["open", "high", "low", "close"]].astype(float)
    if (not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any()
            or (prices["high"] < prices.max(axis=1)).any()
            or (prices["low"] > prices.min(axis=1)).any()):
        raise ValueError("Elliott wave12 OHLC failed strict validation")
    n = len(frame)
    output = {name: np.full(n, np.nan) for name in (
        "lagged_elliott_origin_low", "lagged_elliott_wave1_high", "lagged_elliott_wave2_low",
        "lagged_elliott_origin_index", "lagged_elliott_wave1_index", "lagged_elliott_wave2_index",
        "lagged_elliott_wave2_confirmed_at", "elliott_wave12_trigger_index",
    )}
    output["lagged_elliott_wave12_active"] = np.zeros(n)
    output["elliott_wave12_close_breakout_event"] = np.zeros(n)
    highs, lows, closes = (prices[c].to_numpy() for c in ("high", "low", "close"))
    pivots: list[ElliottPivot] = []
    setup: tuple[ElliottPivot, ElliottPivot, ElliottPivot] | None = None
    consumed: set[tuple[int, int]] = set()
    for at in range(n):
        # Snapshot was stored after at-1. No information from this bar's newly
        # confirmed pivots can participate in its current signal.
        if setup is not None:
            origin, high, correction = setup
            output["lagged_elliott_wave12_active"][at] = 1.0
            for name, value in (
                ("origin_low", origin.price), ("wave1_high", high.price),
                ("wave2_low", correction.price), ("origin_index", origin.index),
                ("wave1_index", high.index), ("wave2_index", correction.index),
                ("wave2_confirmed_at", correction.confirmed_at),
            ):
                output["lagged_elliott_" + name][at] = value
            age = at - correction.confirmed_at
            identity = (origin.index, high.index)
            if age > MAX_ELIGIBLE_AGE or lows[at] <= origin.price:
                setup = None
            elif age >= 1 and closes[at] > high.price and closes[at - 1] <= high.price:
                # Consume a price event even if the separate body/regime gates
                # later deny entry. Never wait for a more favorable later gate.
                if identity not in consumed:
                    consumed.add(identity)
                    output["elliott_wave12_close_breakout_event"][at] = 1.0
                    output["elliott_wave12_trigger_index"][at] = at
                setup = None

        point = _confirmed_pivot(highs, lows, at)
        if point is None:
            continue
        if pivots and pivots[-1].kind == point.kind:
            old = pivots[-1]
            more_extreme = point.price > old.price if point.kind == "high" else point.price < old.price
            if not more_extreme:
                continue
            pivots[-1] = point
        else:
            pivots.append(point)
            pivots = pivots[-3:]
        # Every accepted pivot-state change disarms the old pending setup;
        # invalid new geometry cannot resurrect a previous pending count.
        setup = None
        if point.kind != "low" or len(pivots) != 3:
            continue
        geometry = elliott_wave12_geometry(pivots)
        if geometry is None or (pivots[0].index, pivots[1].index) in consumed:
            continue
        # Validate the whole observed interval, including lows that were not
        # selected as pivots. Subsequent bars are checked incrementally above.
        if (lows[pivots[0].index + 1:at + 1] <= geometry["origin_price"]).any():
            continue
        setup = (pivots[0], pivots[1], pivots[2])
    return {name: pd.Series(values, index=frame.index) for name, values in output.items()}
