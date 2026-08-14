from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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


def _as_utc(value: datetime, *, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _calendar_month_count(window_start: datetime, window_end: datetime) -> int:
    """Count UTC calendar months touched by the half-open evaluation window."""

    last_included = window_end - timedelta(microseconds=1)
    return (
        (last_included.year - window_start.year) * 12
        + (last_included.month - window_start.month)
        + 1
    )


def evaluate_activity(
    entry_times: Iterable[datetime],
    *,
    window_start: datetime,
    window_end: datetime,
    policy: ActivityPolicy = ActivityPolicy(),
) -> ActivityResult:
    """Evaluate strategy activity inside one explicit OOS interval.

    Window semantics are half-open: ``[window_start, window_end)``.  Inputs are
    normalized to UTC before duplicate, boundary, month-coverage, and gap checks
    so equivalent instants expressed with different offsets cannot be counted as
    separate trades.
    """

    start = _as_utc(window_start, name="window_start")
    end = _as_utc(window_end, name="window_end")
    if end <= start:
        raise ValueError("window_end must be after window_start")

    times = [_as_utc(t, name="entry_times") for t in entry_times]
    if len(set(times)) != len(times):
        raise ValueError("entry_times must not contain duplicate timestamps")
    if any(t < start or t >= end for t in times):
        raise ValueError("entry_times must fall within [window_start, window_end)")

    times.sort()
    evaluation_days = (end - start).total_seconds() / 86_400.0
    total_calendar_months = _calendar_month_count(start, end)

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
