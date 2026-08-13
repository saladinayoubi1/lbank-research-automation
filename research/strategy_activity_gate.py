from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import median
from typing import Iterable


@dataclass(frozen=True)
class ActivityPolicy:
    """Screen out statistically sparse strategy candidates before deeper promotion.

    This is a research eligibility gate, not a profitability claim.
    """

    min_oos_trades: int = 40
    min_trades_per_30d: float = 4.0
    min_active_month_ratio: float = 0.50
    max_median_gap_days: float = 14.0


@dataclass(frozen=True)
class ActivityResult:
    eligible: bool
    reasons: tuple[str, ...]
    trade_count: int
    trades_per_30d: float
    active_month_ratio: float
    median_gap_days: float | None


def evaluate_activity(
    entry_times: Iterable[datetime],
    *,
    evaluation_days: float,
    total_calendar_months: int,
    policy: ActivityPolicy = ActivityPolicy(),
) -> ActivityResult:
    times = sorted(entry_times)
    if evaluation_days <= 0:
        raise ValueError("evaluation_days must be > 0")
    if total_calendar_months <= 0:
        raise ValueError("total_calendar_months must be > 0")
    if any(t.tzinfo is None for t in times):
        raise ValueError("entry_times must be timezone-aware")

    trade_count = len(times)
    trades_per_30d = trade_count * 30.0 / evaluation_days
    active_months = len({(t.year, t.month) for t in times})
    active_month_ratio = active_months / total_calendar_months

    if trade_count >= 2:
        gaps = [
            (right - left).total_seconds() / 86_400.0
            for left, right in zip(times, times[1:])
        ]
        median_gap_days = float(median(gaps))
    else:
        median_gap_days = None

    reasons: list[str] = []
    if trade_count < policy.min_oos_trades:
        reasons.append("INSUFFICIENT_OOS_TRADES")
    if trades_per_30d < policy.min_trades_per_30d:
        reasons.append("SIGNAL_FREQUENCY_TOO_LOW")
    if active_month_ratio < policy.min_active_month_ratio:
        reasons.append("TOO_FEW_ACTIVE_MONTHS")
    if median_gap_days is None or median_gap_days > policy.max_median_gap_days:
        reasons.append("TRADE_GAPS_TOO_WIDE")

    return ActivityResult(
        eligible=not reasons,
        reasons=tuple(reasons),
        trade_count=trade_count,
        trades_per_30d=trades_per_30d,
        active_month_ratio=active_month_ratio,
        median_gap_days=median_gap_days,
    )
