"""Pure research-only review of one frozen Wyckoff-style liquidity spring.

Geometry only, not OHLC pivot discovery, trade advice, order admission, or
an executable strategy. All three extrema must be strictly confirmed by
three subsequently CLOSED 15m bars before this function is called.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from typing import Sequence

SCHEMA = "nexus.causal-liquidity-spring-v12-shape/v1"
RESEARCH_ONLY = True
LIVE_ENABLED = False
PAPER_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
MARKET_RUNS = 0

RIGHT_BARS = 3
MAX_PIVOT_SPAN = 96
MAX_CONFIRMATION_AGE = 16
MAX_SWEEP_RATIO = Decimal("0.382")


@dataclass(frozen=True)
class ConfirmedSpringPivot:
    kind: str
    index: int
    confirmed_at: int
    price: Decimal | float | int | str


def review_spring_shape(
    pivots: Sequence[ConfirmedSpringPivot],
    decision_index: int,
) -> dict | None:
    """Accept latest causally confirmed L0-H1-L2 geometry or return None.

    This does NOT inspect OHLC path, infer a spring entry, or relax cost gates.
    Those checks belong in a separate streaming feature builder in future work.
    """
    if type(decision_index) is not int or decision_index < 0:
        raise ValueError("decision_index must be a non-negative exact integer")
    if len(pivots) < 3:
        return None
    selected = tuple(pivots[-3:])
    if tuple(p.kind for p in selected) != ("low", "high", "low"):
        return None
    if any(type(p.index) is not int or type(p.confirmed_at) is not int
           or p.index < 0 or p.confirmed_at != p.index + RIGHT_BARS
           or p.confirmed_at >= decision_index for p in selected):
        return None
    l0, h1, l2 = selected
    if not (l0.index < h1.index < l2.index):
        return None
    if l2.index - l0.index > MAX_PIVOT_SPAN:
        return None
    age = decision_index - l2.confirmed_at
    if not 1 <= age <= MAX_CONFIRMATION_AGE:
        return None
    try:
        a, b, c = (Decimal(str(p.price)) for p in selected)
    except (ValueError, TypeError, InvalidOperation):
        return None
    if not all(v.is_finite() and v > 0 for v in (a, b, c)):
        return None
    if not b > a > c:
        return None
    with localcontext() as ctx:
        ctx.prec = 50
        response = b - a
        sweep = a - c
        if response <= 0 or sweep <= 0:
            return None
        depth = sweep / response
        if not (Decimal(0) < depth <= MAX_SWEEP_RATIO):
            return None
    return {
        "schema": SCHEMA,
        "identity": (l0.index, l2.index),
        "L0": a, "H1": b, "L2": c,
        "sweep_depth_ratio": depth,
        "L0_index": l0.index,
        "H1_index": h1.index,
        "L2_index": l2.index,
        "confirmed_at": l2.confirmed_at,
        "earliest_eligible_decision": l2.confirmed_at + 1,
        "last_eligible_decision": l2.confirmed_at + MAX_CONFIRMATION_AGE,
        "reclaim_level": a,
        "invalidation_level": c,
        "cost_span": b - c,
        "path_verified": False,
        "signal_generated": False,
        "research_only": True,
        "live_enabled": False,
    }
