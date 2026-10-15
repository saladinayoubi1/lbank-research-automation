"""Causal, research-only five-swing features from completed UTC15m OHLC.

Timestamp means bar CLOSE, not bar open. The caller owns that convention and
must exclude the currently forming bar. A newly confirmed pivot affects only
the next decision. This does not classify recursive Elliott subdivisions or
register a strategy, place an order, or qualify profitability.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from nexus_elliott_five_swing_review import (
    ConfirmedPivot, MAX_AGE, WIDTH, review_five_swing_setup,
)
from nexus_causal_macro_retest_features import stress_cost_screen

RESEARCH_ONLY = True
EXECUTION_INTEGRATED = False
COMPLETE_ELLIOTT_COUNT = False
STEP_NS = 900_000_000_000


@dataclass(frozen=True)
class PendingSetup:
    pivots: tuple[ConfirmedPivot, ...]
    retracement: float


def _validated(closed_frame: pd.DataFrame) -> np.ndarray:
    if not {"timestamp", "open", "high", "low", "close"}.issubset(closed_frame.columns):
        raise ValueError("Elliott five-swing input missing timestamp/OHLC")
    try:
        if any(pd.Timestamp(t).tzinfo is None for t in closed_frame["timestamp"]):
            raise ValueError("Elliott five-swing timestamps require an explicit timezone")
        times = pd.to_datetime(closed_frame["timestamp"], utc=True, errors="raise")
        ns = times.to_numpy(dtype="datetime64[ns]").astype(np.int64)
        prices = closed_frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    except (TypeError, OverflowError) as exc:
        raise ValueError("Elliott five-swing invalid timestamp/OHLC") from exc
    if (times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing
            or (np.diff(ns) != STEP_NS).any() or (ns % STEP_NS != 0).any()):
        raise ValueError("Elliott five-swing requires a complete aligned UTC15m grid")
    if (not np.isfinite(prices).all() or (prices <= 0).any()
            or (prices[:, 1] < prices.max(axis=1)).any()
            or (prices[:, 2] > prices.min(axis=1)).any()):
        raise ValueError("Elliott five-swing OHLC failed strict validation")
    return prices


def _confirmed_pivot(highs: np.ndarray, lows: np.ndarray, at: int) -> ConfirmedPivot | None:
    if at < WIDTH * 2:
        return None
    center, start = at - WIDTH, at - WIDTH * 2
    other_highs = np.concatenate((highs[start:center], highs[center + 1:at + 1]))
    other_lows = np.concatenate((lows[start:center], lows[center + 1:at + 1]))
    is_high = bool((highs[center] > other_highs).all())
    is_low = bool((lows[center] < other_lows).all())
    # A tied extremum is not confirmed. An outside bar with both extrema has
    # unknowable intrabar order, so cannot supply either pivot in this scope.
    if is_high == is_low:
        return None
    kind, price = ("high", highs[center]) if is_high else ("low", lows[center])
    return ConfirmedPivot(kind, center, at, float(price))


def _path_rejection(points: tuple[ConfirmedPivot, ...], highs: np.ndarray,
                    lows: np.ndarray, at: int) -> str | None:
    origin, one, two, three, four, five, correction = points
    if (lows[origin.index + 1:at + 1] <= origin.price).any():
        return "origin_path_breach"
    if (lows[one.index:three.index + 1] < two.price).any():
        return "second_low_not_path_minimum"
    if (lows[three.index:five.index + 1] <= one.price).any():
        return "fourth_path_overlap"
    if (lows[three.index:five.index + 1] < four.price).any():
        return "fourth_low_not_path_minimum"
    if (lows[five.index:at + 1] < correction.price).any():
        return "correction_low_not_path_minimum"
    for left, right, peak in ((origin, two, one), (two, four, three), (four, correction, five)):
        if (highs[left.index:right.index + 1] > peak.price).any():
            return "swing_high_not_path_maximum"
    return None


def build_lagged_elliott_five_swing_features(
    closed_frame: pd.DataFrame, *, diagnostics: list[dict] | None = None,
) -> dict[str, pd.Series]:
    """Previous setup -> closed-bar invalidation/event -> future pivot state.

The first fresh CLOSE cross consumes (origin index, fifth-high index), even
when the separate prospective stress-cost hypothesis fails. Cost feasibility
uses current close and strictly previous-bar ATR; it is not an entry decision
and cannot know the next open or actual fill. No archive or executor is used.
"""
    prices = _validated(closed_frame)
    _, highs, lows, closes = prices.T
    n = len(closed_frame)
    atr = pd.Series(highs - lows).shift(1).rolling(14, min_periods=14).mean().to_numpy()
    numeric = (
        "lagged_elliott5_origin_low", "lagged_elliott5_wave1_high", "lagged_elliott5_wave2_low",
        "lagged_elliott5_origin_index", "lagged_elliott5_wave1_index", "lagged_elliott5_wave2_index",
        "lagged_elliott5_confirmed_at", "lagged_elliott5_retracement",
        "elliott5_trigger_index", "elliott5_decision_atr", "elliott5_flat_cost", "elliott5_target_net",
    )
    flags = (
        "lagged_elliott5_active", "elliott5_close_breakout_event", "elliott5_cost_feasible",
        "elliott5_invalidated", "elliott5_expired", "elliott5_path_rejected",
    )
    output = {name: np.full(n, np.nan) for name in numeric}
    output.update({name: np.zeros(n, dtype=bool) for name in flags})
    pivots: list[ConfirmedPivot] = []
    setup: PendingSetup | None = None
    consumed: set[tuple[int, int]] = set()

    def record(at: int, action: str, **details) -> None:
        if diagnostics is not None:
            diagnostics.append({"decision_index": at, "action": action, **details})

    for at in range(n):
        # Snapshot is exactly the state stored after at-1, including on the
        # bar that expires/invalidates it. Event flags determine eligibility.
        if setup is not None:
            origin, *_, five, correction = setup.pivots
            identity = (origin.index, five.index)
            output["lagged_elliott5_active"][at] = True
            for suffix, value in (
                ("origin_low", origin.price), ("wave1_high", five.price),
                ("wave2_low", correction.price), ("origin_index", origin.index),
                ("wave1_index", five.index), ("wave2_index", correction.index),
                ("confirmed_at", correction.confirmed_at), ("retracement", setup.retracement),
            ):
                output["lagged_elliott5_" + suffix][at] = value
            age = at - correction.confirmed_at
            if lows[at] <= origin.price or lows[at] < correction.price:
                output["elliott5_invalidated"][at] = True
                reason = "origin_breach" if lows[at] <= origin.price else "correction_low_breach"
                record(at, "invalidated", identity=list(identity), reason=reason)
                setup = None
            elif age > MAX_AGE:
                output["elliott5_expired"][at] = True
                record(at, "expired", identity=list(identity))
                setup = None
            elif age >= 1 and closes[at - 1] <= five.price < closes[at]:
                consumed.add(identity)
                output["elliott5_close_breakout_event"][at] = True
                output["elliott5_trigger_index"][at] = at
                screen = stress_cost_screen(float(closes[at]), float(atr[at]),
                                            float(five.price - origin.price))
                output["elliott5_decision_atr"][at] = atr[at]
                output["elliott5_cost_feasible"][at] = screen["feasible"]
                output["elliott5_flat_cost"][at] = screen.get("flat_cost", np.nan)
                output["elliott5_target_net"][at] = screen.get("target_net", np.nan)
                record(at, "price_event_consumed", identity=list(identity), cost_screen=screen)
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
            pivots = pivots[-7:]
        setup = None
        record(at, "pivot_accepted", pivot_kind=point.kind, pivot_index=point.index)
        if point.kind != "low" or len(pivots) != 7:
            continue
        # at+1 is used ONLY to prepare the next state. No output at 'at' can
        # use the pivot whose right-hand confirmation just became visible.
        geometry = review_five_swing_setup(pivots, at + 1)
        if geometry is None:
            continue
        identity = geometry["identity"]
        if identity in consumed:
            record(at, "consumed_identity", identity=list(identity))
            continue
        points = tuple(pivots)
        reason = _path_rejection(points, highs, lows, at)
        if reason is not None:
            output["elliott5_path_rejected"][at] = True
            record(at, "path_rejected", identity=list(identity), reason=reason)
            continue
        setup = PendingSetup(points, float(geometry["retracement"]))
        record(at, "setup_stored_for_next_bar", identity=list(identity),
               earliest_decision_index=at + 1)
    return {name: pd.Series(values, index=closed_frame.index) for name, values in output.items()}
