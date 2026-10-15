"""Closed-pivot structural review only; no entry signal or trading integration.

Five swings are not a complete recursive Elliott 5-3-5-3-5 classification.
This checks an explicitly limited, non-diagonal, non-truncated bullish shape.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Sequence

RESEARCH_ONLY = True
EXECUTION_INTEGRATED = False
WIDTH = 3
MAX_SPAN = 192
MAX_AGE = 32


@dataclass(frozen=True)
class ConfirmedPivot:
    kind: str
    index: int
    confirmed_at: int
    price: str | int | float | Decimal


def review_five_swing_setup(
    pivots: Sequence[ConfirmedPivot], decision_index: int
) -> dict | None:
    """Use only pivots known before this decision; inspect the latest seven.

The caller must supply causally extracted pivots. This prototype cannot verify
the source OHLC path, recursive degrees, fresh breakout, costs, or fills.
"""
    if type(decision_index) is not int or decision_index < 0:
        raise ValueError("decision_index must be a nonnegative integer")
    known = [p for p in pivots if type(p.confirmed_at) is int
             and p.confirmed_at < decision_index]
    if len(known) < 7:
        return None
    group = known[-7:]
    if tuple(p.kind for p in group) != ("low", "high", "low", "high", "low", "high", "low"):
        return None
    if any(type(p.index) is not int or p.index < 0 or p.confirmed_at != p.index + WIDTH
           for p in group):
        return None
    if any(b.index <= a.index for a, b in zip(group, group[1:])):
        return None
    if group[-1].index - group[0].index > MAX_SPAN:
        return None
    age = decision_index - group[-1].confirmed_at
    if not 1 <= age <= MAX_AGE:
        return None
    try:
        values = tuple(Decimal(str(p.price)) for p in group)
    except (InvalidOperation, ValueError):
        return None
    if any(not p.is_finite() or p <= 0 for p in values):
        return None
    origin, one, two, three, four, five, correction = values
    if not (origin < two < one < three and one < four < three < five
            and origin < correction < five):
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        lengths = (one - origin, three - two, five - four)
        relative = (lengths[0] / origin, lengths[1] / two, lengths[2] / four)
        # Strictly exclude the shortest/tied-shortest third swing in BOTH
        # arithmetic and relative price terms. This is a conservative scope
        # choice, not an exhaustive classification of every Elliott variant.
        if lengths[1] <= min(lengths[0], lengths[2]) or relative[1] <= min(relative[0], relative[2]):
            return None
        retracement = (five - correction) / (five - origin)
        if not Decimal("0.382") <= retracement <= Decimal("0.786"):
            return None
    return {
        "origin": origin, "wave1_high": five, "wave2_low": correction,
        "retracement": retracement,
        "identity": (group[0].index, group[5].index),
        "confirmed_at": group[6].confirmed_at,
        "earliest_decision_index": group[6].confirmed_at + 1,
        "complete_elliott_count": False, "entry_signal": False,
    }
