"""Independent source-bound seven-pivot Elliott PROOF, not an Elliott counter.

Consumes one immutable prefix of UTC 15m OPEN-timestamped completed OHLC.
Rebuilds the original seven accepted strict local-extrema pivots and checks
every in-scope structural path constraint from raw candles.  Deliberately
not a recursive 5-3-5-3-5 classifier, signal, execution engine, or backtest.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Sequence

import numpy as np
import pandas as pd

from nexus_elliott_five_swing_review import (
    ConfirmedPivot, MAX_AGE, MAX_SPAN, WIDTH, review_five_swing_setup,
)

RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ELIGIBLE = False
ENTRY_SIGNAL = False
RECURSIVE_ELLIOTT_PROVEN = False
_BAR_DELTA = pd.Timedelta(minutes=15)


@dataclass(frozen=True)
class SourceBoundVerdict:
    source_bound: bool
    seven_pivots_confirmed: bool
    recursive_elliott_proven: bool
    paper_eligible: bool
    entry_signal: bool
    reason: str
    decision_index: int
    pivot_indices: tuple[int, ...] = ()
    confirmation_indices: tuple[int, ...] = ()
    structure_id: tuple[int, int] | None = None


def _closed_history(frame: pd.DataFrame, decision_index: int,
                    decision_close_utc: object) -> tuple[np.ndarray, pd.DatetimeIndex]:
    if type(decision_index) is not int or decision_index < 0:
        raise ValueError("decision index must be a nonnegative int")
    # The first source bar represents absolute index 0. Relative subwindows
    # cannot certify that older competing extrema/pivots did not exist.
    if not isinstance(frame, pd.DataFrame) or not isinstance(frame.index, pd.RangeIndex) or (
        frame.index.start != 0 or frame.index.step != 1
    ):
        raise ValueError("a complete index-zero source prefix is required")
    if len(frame) != decision_index + 1:
        raise ValueError("future tail / incomplete closed decision prefix is prohibited")
    if not {"timestamp", "open", "high", "low", "close"}.issubset(frame):
        raise ValueError("missing source UTC OPEN timestamp / OHLC")
    raw_time = frame["timestamp"].tolist()
    if not all(pd.Timestamp(t).tzinfo is not None and pd.Timestamp(t).utcoffset() is not None
               for t in raw_time):
        raise ValueError("all source timestamps must be timezone-aware")
    times = pd.DatetimeIndex(pd.to_datetime(raw_time, utc=True, errors="raise"))
    if times.hasnans or not times.is_monotonic_increasing or not times.is_unique:
        raise ValueError("invalid or duplicate source time")
    clock = times.asi8
    if len(clock) > 1 and (np.diff(clock) != _BAR_DELTA.value).any():
        raise ValueError("incomplete 15m source grid")
    if (clock % _BAR_DELTA.value != 0).any():
        raise ValueError("source OPEN not aligned to UTC 15m")
    if not isinstance(decision_close_utc, (pd.Timestamp,)) and not hasattr(
        decision_close_utc, "tzinfo"
    ):
        raise ValueError("decision close must be explicitly timezone-aware")
    stamp = pd.Timestamp(decision_close_utc)
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError("decision close must be explicitly timezone-aware")
    if times[-1] + _BAR_DELTA != stamp.tz_convert("UTC"):
        raise ValueError("future/incomplete candle versus decision close")
    prices = frame[["open", "high", "low", "close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        raise ValueError("nonfinite/nonpositive OHLC")
    op, hi, lo, cl = prices.T
    if (hi < np.maximum.reduce((op, lo, cl))).any() or (
        lo > np.minimum.reduce((op, hi, cl))
    ).any():
        raise ValueError("invalid bar OHLC bounds")
    return prices, times


def _independent_selected_pivots(prices: np.ndarray,
                                 decision_index: int) -> tuple[ConfirmedPivot, ...]:
    """Reconstruct accepted pivot history known BEFORE decision bar d.

    Uses explicit six-neighbor strict local extrema and the original
    alternating/more-extreme-same-kind rule, independently of feature state.
    The currently closed decision bar may not be used to confirm the pivot.
    """
    hi = prices[:, 1]
    lo = prices[:, 2]
    pivots: list[ConfirmedPivot] = []
    for confirmed_at in range(2 * WIDTH, decision_index):
        center = confirmed_at - WIDTH
        neighbors = [i for i in range(center - WIDTH, confirmed_at + 1) if i != center]
        higher = all(hi[center] > hi[i] for i in neighbors)
        lower = all(lo[center] < lo[i] for i in neighbors)
        if higher == lower:
            continue  # ties and unknowable double-extrema outside scope
        point = ConfirmedPivot("high" if higher else "low", center, confirmed_at,
                               float(hi[center] if higher else lo[center]))
        if pivots and pivots[-1].kind == point.kind:
            prev = pivots[-1]
            replace = (point.price > prev.price if point.kind == "high"
                       else point.price < prev.price)
            if replace:
                pivots[-1] = point
            continue
        pivots.append(point)
        pivots = pivots[-7:]
    return tuple(pivots)


def _independent_path_reason(prices: np.ndarray,
                             pivots: Sequence[ConfirmedPivot],
                             through: int) -> str | None:
    hi, lo = prices[:, 1], prices[:, 2]
    origin, one, two, three, four, five, correction = pivots
    # Parent frozen nonoverlap and local path semantics; no tuning.
    if (lo[origin.index + 1:through + 1] <= origin.price).any():
        return "ORIGIN_BREACHED"
    if (lo[one.index:three.index + 1] < two.price).any():
        return "SECOND_WAVE_LOW_NOT_MINIMUM"
    if (lo[three.index:five.index + 1] <= one.price).any():
        return "FOURTH_WAVE_OVERLAPS_FIRST"
    if (lo[three.index:five.index + 1] < four.price).any():
        return "FOURTH_WAVE_LOW_NOT_MINIMUM"
    if (lo[five.index:through + 1] < correction.price).any():
        return "CORRECTION_LOW_NOT_MINIMUM"
    for left, right, peak in (
        (origin, two, one), (two, four, three), (four, correction, five)
    ):
        if (hi[left.index:right.index + 1] > peak.price).any():
            return "SWING_HIGH_NOT_MAXIMUM"
    return None


def certify_seven_pivots_from_closed_15m(
    closed_15m: pd.DataFrame,
    pivots: Sequence[ConfirmedPivot],
    decision_index: int,
    *,
    decision_close_utc: object,
) -> SourceBoundVerdict:
    """Certify complete causal prefix and seven current accepted extrema.

    Does not perform strategy event selection, count recursive subdivisions,
    predict performance, or authorize any Paper/Live execution.  Incomplete
    raw evidence raises ValueError rather than guessing.
    """
    prices, times = _closed_history(closed_15m, decision_index, decision_close_utc)
    reconstructed = _independent_selected_pivots(prices, decision_index)
    baseline = dict(
        source_bound=False, seven_pivots_confirmed=False,
        recursive_elliott_proven=False, paper_eligible=False,
        entry_signal=False, decision_index=decision_index,
    )
    if len(reconstructed) < 7:
        return SourceBoundVerdict(**baseline, reason="FEWER_THAN_SEVEN_ACCEPTED_PIVOTS")
    if len(pivots) != 7:
        return SourceBoundVerdict(**baseline, reason="SEVEN_EXPECTED_PIVOTS_REQUIRED")
    for want, actual in zip(pivots, reconstructed):
        if not isinstance(want, ConfirmedPivot) or (
            type(want.index) is not int or type(want.confirmed_at) is not int
        ) or (want.kind, want.index, want.confirmed_at) != (
            actual.kind, actual.index, actual.confirmed_at
        ):
            return SourceBoundVerdict(**baseline, reason="PIVOT_OR_CONFIRMATION_MISMATCH")
        try:
            claimed = Decimal(str(want.price))
            observed = Decimal(str(actual.price))
        except (InvalidOperation, ValueError, TypeError):
            return SourceBoundVerdict(**baseline, reason="PIVOT_PRICE_MALFORMED")
        if not claimed.is_finite() or claimed != observed:
            return SourceBoundVerdict(**baseline, reason="PIVOT_PRICE_MISMATCH")

    geometry = review_five_swing_setup(reconstructed, decision_index)
    if geometry is None:
        return SourceBoundVerdict(**baseline, reason="FROZEN_GEOMETRY_NOT_ELIGIBLE")
    path_reason = _independent_path_reason(prices, reconstructed, decision_index)
    if path_reason is not None:
        return SourceBoundVerdict(**baseline, reason=path_reason)
    # Exact one-shot first breakout remains separately evaluated in V14;
    # this certifier does not emit a breakout event or order.
    return SourceBoundVerdict(
        source_bound=True, seven_pivots_confirmed=True,
        recursive_elliott_proven=False, paper_eligible=False,
        entry_signal=False, reason="SOURCE_BOUND_LIMITED_SEVEN_PIVOT_SHAPE",
        decision_index=decision_index,
        pivot_indices=tuple(x.index for x in reconstructed),
        confirmation_indices=tuple(x.confirmed_at for x in reconstructed),
        structure_id=geometry["identity"],
    )
