"""Fixed research-only bullish Butterfly detection from causally confirmed pivots.

An extremum at j becomes visible only at the CLOSE of j+3. Its pattern event is
lagged one further completed bar; a consumer can then enter at the next OPEN.
Past emitted output is immutable even when later confirmed same-side pivots
replace the latest pivot in the future detector state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import json
from pathlib import Path

import numpy as np
import pandas as pd

PREREGISTRATION = Path(__file__).resolve().parent / "research" / "causal_bullish_butterfly_v8_preregistration.json"
PARAMETERS = json.loads(PREREGISTRATION.read_text(encoding="utf-8"))
if (PARAMETERS["schema"] != "nexus.causal-bullish-butterfly.v1"
        or PARAMETERS["pivot_left_bars"] != 3 or PARAMETERS["pivot_right_bars"] != 3
        or PARAMETERS["max_pattern_span_bars"] != 192
        or PARAMETERS["ab_over_xa"] != [0.756, 0.816]
        or PARAMETERS["bc_over_ab"] != [0.382, 0.886]
        or PARAMETERS["ad_over_xa"] != [1.24, 1.30]
        or PARAMETERS["cd_over_bc"] != [1.618, 2.618]
        or PARAMETERS["cd_over_ab"] != [1.0, 1.618]
        or PARAMETERS["risk_variant"] != 0
        or PARAMETERS["live_enabled"] is not False
        or PARAMETERS["auto_demo_promotion"] is not False):
    raise ValueError("Frozen Butterfly preregistration differs")

WIDTH = 3
MAX_SPAN = 192
REBOUND_XA = 0.10
RATIO_ROUNDOFF = 1e-12  # floating representation only, not a tunable ratio tolerance


@dataclass(frozen=True)
class ConfirmedPivot:
    kind: str
    index: int
    confirmed_at: int
    price: float


def bullish_butterfly_geometry(pivots: Sequence[ConfirmedPivot]) -> dict[str, float] | None:
    """Price geometry only; never claims pattern profitability or future fills."""
    if len(pivots) != 5 or tuple(p.kind for p in pivots) != ("low", "high", "low", "high", "low"):
        return None
    if any(b.index <= a.index for a, b in zip(pivots, pivots[1:])):
        return None
    if any(p.confirmed_at < p.index + WIDTH for p in pivots):
        return None
    if pivots[-1].index - pivots[0].index > MAX_SPAN:
        return None
    prices = np.asarray([p.price for p in pivots], dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        return None
    x, a, b, c, d = map(float, prices)
    if not d < x < b < c < a:
        return None
    xa, ab, bc, cd, ad = a-x, a-b, c-b, c-d, a-d
    ratios = {"ab_over_xa": ab/xa, "bc_over_ab": bc/ab,
              "ad_over_xa": ad/xa, "cd_over_bc": cd/bc, "cd_over_ab": cd/ab}
    if any(not lo-RATIO_ROUNDOFF <= ratios[key] <= hi+RATIO_ROUNDOFF for key, (lo, hi) in
           ((key, PARAMETERS[key]) for key in ratios)):
        return None
    return {**ratios, "d_price": d, "xa_size": xa, "rebound_price": d + REBOUND_XA*xa}


def _confirmed_pivot(highs: np.ndarray, lows: np.ndarray, at: int) -> ConfirmedPivot | None:
    if at < WIDTH*2:
        return None
    center = at-WIDTH
    lo, hi = center-WIDTH, at+1
    other_highs = np.concatenate((highs[lo:center], highs[center+1:hi]))
    other_lows = np.concatenate((lows[lo:center], lows[center+1:hi]))
    is_high = bool((highs[center] > other_highs).all())
    is_low = bool((lows[center] < other_lows).all())
    # An outside bar may be both extremes; OHLC has no reliable intra-bar order.
    if is_high == is_low:
        return None
    kind, price = ("high", highs[center]) if is_high else ("low", lows[center])
    return ConfirmedPivot(kind, center, at, float(price))


def build_lagged_butterfly_features(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Single-pass delayed events on a complete closed 15m OHLC grid."""
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError("Butterfly input missing timestamp/OHLC")
    t = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if (t.isna().any() or t.duplicated().any() or not t.is_monotonic_increasing
            or not (t.diff().dropna() == pd.Timedelta(minutes=15)).all()
            or any(value.value % 900_000_000_000 for value in t)):
        raise ValueError("Butterfly requires a complete aligned UTC15m grid")
    ohlc = frame[["open", "high", "low", "close"]].astype(float)
    if (not np.isfinite(ohlc.to_numpy()).all() or (ohlc <= 0).any().any()
            or (ohlc["high"] < ohlc.max(axis=1)).any()
            or (ohlc["low"] > ohlc.min(axis=1)).any()):
        raise ValueError("Butterfly OHLC failed strict validation")
    n = len(frame)
    event = np.zeros(n)
    rebound = np.full(n, np.nan)
    d_index = np.full(n, np.nan)
    confirmation = np.full(n, np.nan)
    highs, lows = ohlc["high"].to_numpy(), ohlc["low"].to_numpy()
    pivots: list[ConfirmedPivot] = []
    seen: set[tuple[int, ...]] = set()
    for at in range(n):
        point = _confirmed_pivot(highs, lows, at)
        if point is None:
            continue
        if pivots and pivots[-1].kind == point.kind:
            prior = pivots[-1]
            more_extreme = point.price > prior.price if point.kind == "high" else point.price < prior.price
            if not more_extreme:
                continue
            pivots[-1] = point
        else:
            pivots.append(point)
            pivots = pivots[-5:]
        if point.kind != "low" or len(pivots) != 5:
            continue
        identity = tuple(p.index for p in pivots)
        if identity in seen:
            continue
        geometry = bullish_butterfly_geometry(pivots)
        if geometry is None:
            continue
        seen.add(identity)
        event[at] = 1.0
        rebound[at] = geometry["rebound_price"]
        d_index[at] = point.index
        confirmation[at] = at
    # Context cannot depend on the current decision bar. Empty/early rows stay unavailable.
    return {
        "lagged_bullish_butterfly_event": pd.Series(event, index=frame.index).shift(1).fillna(0.0),
        "lagged_butterfly_rebound_price": pd.Series(rebound, index=frame.index).shift(1),
        "lagged_butterfly_d_index": pd.Series(d_index, index=frame.index).shift(1),
        "lagged_butterfly_confirmed_at": pd.Series(confirmation, index=frame.index).shift(1),
    }

