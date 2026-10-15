"""V14 Elliott candidate QUALITY DIAGNOSTIC, not a trading strategy or producer.

No order, factory registration, runtime signal, market fetch or history retuning.
Uses the established 7-pivot causal structural reviewer.  This narrow count is
NOT a recursive Elliott count.  Market profitability is unknown.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from typing import Sequence

from nexus_elliott_five_swing_review import ConfirmedPivot, review_five_swing_setup

RESEARCH_ONLY = True
LIVE_ENABLED = False
AUTO_DEMO = False
FACTORY_REGISTERED = False
ENTRY_SIGNAL = False
COMPLETE_RECURSIVE_ELLIOTT_COUNT = False

# These are UNMODIFIED parent simulation assumptions, not newly tuned values.
STRESS_FEE_PER_LEG = Decimal("0.0025")
STRESS_SLIP_PER_LEG = Decimal("0.0015")
PARENT_REWARD_RISK = Decimal("2")


def _positive_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(name + " must be a finite positive number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(name + " must be a finite positive number") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError(name + " must be a finite positive number")
    return result


def _nonnegative_decimal(value: object, name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(name + " must be a finite nonnegative number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(name + " must be a finite nonnegative number") from exc
    if not result.is_finite() or result < 0:
        raise ValueError(name + " must be a finite nonnegative number")
    return result


def _closed_utc(value: datetime, minutes: int, name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(name + " must be an aware completed-candle close")
    utc = value.astimezone(timezone.utc)
    if utc.second or utc.microsecond or utc.minute % minutes:
        raise ValueError(name + " is not aligned to a closed candle")
    if minutes == 240 and utc.hour % 4:
        raise ValueError(name + " is not on the UTC 4h grid")
    return utc


def causal_asof_check(
    decision_close: datetime,
    last_completed_h1_close: datetime,
    last_completed_h4_close: datetime,
) -> dict:
    """Fail closed if a higher-timeframe feature could see a forming candle."""
    decision = _closed_utc(decision_close, 15, "decision_close")
    h1 = _closed_utc(last_completed_h1_close, 60, "last_completed_h1_close")
    h4 = _closed_utc(last_completed_h4_close, 240, "last_completed_h4_close")
    if h1 > decision or h4 > decision:
        raise ValueError("higher-timeframe candle closes after decision")
    if decision - h1 >= timedelta(hours=1):
        raise ValueError("stale/missing completed 1h context")
    if decision - h4 >= __import__("datetime").timedelta(hours=4):
        raise ValueError("stale/missing completed 4h context")
    return {"decision_utc": decision.isoformat(), "h1_closed_utc": h1.isoformat(),
            "h4_closed_utc": h4.isoformat(), "causal_asof_ok": True}


def true_range(high: object, low: object, previous_close: object) -> Decimal:
    """Actual True Range, distinct from the previous mean(high-low) named atr."""
    h = _positive_decimal(high, "high")
    l = _positive_decimal(low, "low")
    pc = _positive_decimal(previous_close, "previous_close")
    if h < l:
        raise ValueError("invalid OHLC high < low")
    return max(h - l, abs(h - pc), abs(l - pc))


def _audit_post_correction_closes(
    path: Sequence[tuple[datetime, object, object]],
    *,
    correction_index: int,
    correction_confirmed_at: int,
    decision_index: int,
    decision_close_utc: datetime,
    correction_low: Decimal,
    fifth_high: Decimal,
    previous_close: Decimal,
    decision_close: Decimal,
    decision_low: Decimal,
) -> str | None:
    """Verify complete close/low chronology since correction pivot center.

    This is a bounded post-correction check, NOT full pre-correction OHLC
    extraction or proof of a recursive Elliott wave count. The supplied
    evidence still needs independent provenance and source hashes.
    """
    expected = decision_index - correction_index + 1
    if expected < 2 or len(path) != expected:
        raise ValueError("complete post-correction closed path required")
    start_close = decision_close_utc - timedelta(minutes=15 * (expected - 1))
    values: list[tuple[Decimal, Decimal]] = []
    for offset, bar in enumerate(path):
        if not isinstance(bar, (tuple, list)) or len(bar) != 3:
            raise ValueError("closed path must supply timestamp, low and close")
        stamp = _closed_utc(bar[0], 15, "post-correction closed path")
        if stamp != start_close + timedelta(minutes=15 * offset):
            raise ValueError("post-correction path UTC chronology incomplete/mismatched")
        bar_low = _positive_decimal(bar[1], "post-correction low")
        bar_close = _positive_decimal(bar[2], "post-correction close")
        if bar_low > bar_close:
            raise ValueError("post-correction OHLC low > close")
        values.append((bar_low, bar_close))
    if values[0][0] != correction_low:
        raise ValueError("correction pivot low differs from source path")
    if (values[-1][0], values[-1][1]) != (decision_low, decision_close):
        raise ValueError("decision low/close differs from source path")
    if values[-2][1] != previous_close:
        raise ValueError("previous close differs from source path")
    for offset, (bar_low, bar_close) in enumerate(values):
        index = correction_index + offset
        if offset > 0 and bar_low <= correction_low:
            return "POST_CORRECTION_LOW_ALREADY_INVALIDATED"
        if correction_confirmed_at < index < decision_index and bar_close > fifth_high:
            return "FIRST_BREAK_ALREADY_CONSUMED"
    return None


def review_quality_observation(
    pivots: Sequence[ConfirmedPivot],
    decision_index: int,
    *,
    decision_close_utc: datetime,
    h1_closed_utc: datetime,
    h4_closed_utc: datetime,
    previous_close_price: object,
    decision_close_price: object,
    decision_low_price: object,
    post_correction_closed_path: Sequence[tuple[datetime, object, object]],
    prior_14_true_ranges: Sequence[object],
    h4_closed_up: bool,
    h1_normalized_range_ok: bool,
    actual_traded_volume_ratio: object | None = None,
) -> dict:
    """Assess ONE completed-bar observation; never approve execution.

    Structural stop uses the confirmed correction LOW instead of arbitrary
    1.5 * mean(high-low).  A projection at decision-close cannot predict the
    next-open fill; actual gaps/stops must be independently audited later.
    The traded-volume ratio (when supplied) is not h1_normalized_range_ok.
    Requires the *entire* timestamped post-correction low/close sequence to
    detect earlier invalidation and prior close-break consumption. No claim
    of complete original-wave raw-OHLC verification or external data integrity.
    """
    if type(decision_index) is not int or decision_index < 0:
        raise ValueError("decision_index must be nonnegative int")
    if type(h4_closed_up) is not bool or type(h1_normalized_range_ok) is not bool:
        raise ValueError("higher-timeframe contexts require explicit booleans")
    times = causal_asof_check(decision_close_utc, h1_closed_utc, h4_closed_utc)
    previous = _positive_decimal(previous_close_price, "previous_close_price")
    close = _positive_decimal(decision_close_price, "decision_close_price")
    low = _positive_decimal(decision_low_price, "decision_low_price")
    if low > close:
        raise ValueError("decision low cannot exceed close")
    if len(prior_14_true_ranges) != 14:
        raise ValueError("exactly 14 historical completed true ranges required")
    past_tr = tuple(_nonnegative_decimal(x, "completed true range") for x in prior_14_true_ranges)
    if sum(past_tr) <= 0:
        raise ValueError("true range baseline must have positive mean")
    if actual_traded_volume_ratio is not None:
        ratio = _nonnegative_decimal(actual_traded_volume_ratio, "traded volume ratio")
    else:
        ratio = None

    report = {
        **times, "study_eligible": False, "entry_signal": False, "paper_eligible": False,
        "live_enabled": False, "complete_elliott_count": False,
        "recursive_wave_degree_verified": False, "stop_type": "confirmed_correction_low",
        "range_label": "completed_1h_normalized_candle_range_not_traded_volume",
        "actual_traded_volume_ratio": str(ratio) if ratio is not None else None,
        "prior_true_range_mean": str(sum(past_tr) / Decimal(14)),
        "reasons": [],
    }
    geometry = review_five_swing_setup(pivots, decision_index)
    if geometry is None:
        report["reasons"].append("SEVEN_PIVOT_STRUCTURE_NOT_CONFIRMED")
        return report
    report["event_id"] = list(geometry["identity"])
    report["pivot_confirmed_at_index"] = geometry["confirmed_at"]
    path_reason = _audit_post_correction_closes(
        post_correction_closed_path,
        correction_index=pivots[-1].index,
        correction_confirmed_at=geometry["confirmed_at"],
        decision_index=decision_index,
        decision_close_utc=times["decision_utc"] and
        datetime.fromisoformat(times["decision_utc"]),
        correction_low=geometry["wave2_low"],
        fifth_high=geometry["wave1_high"],
        previous_close=previous, decision_close=close, decision_low=low,
    )
    if path_reason is not None:
        report["reasons"].append(path_reason)
    if not (previous <= geometry["wave1_high"] < close):
        report["reasons"].append("NO_FIRST_CLOSED_BREAKOUT")
    if low <= geometry["wave2_low"]:
        report["reasons"].append("CORRECTION_LOW_TOUCHED_OR_BROKEN")
    if not h4_closed_up:
        report["reasons"].append("H4_CONTEXT_FALSE")
    if not h1_normalized_range_ok:
        report["reasons"].append("H1_NORMALIZED_RANGE_CONTEXT_FALSE")
    if report["reasons"]:
        return report

    with localcontext() as ctx:
        ctx.prec = 40
        # For diagnostic comparability only: original parent's 2R and stress
        # costs. This is NOT a next-open fill or a calibrated edge.
        entry = close * (Decimal(1) + STRESS_SLIP_PER_LEG)
        structural_stop = geometry["wave2_low"]
        if entry <= structural_stop:
            report["reasons"].append("NO_POSITIVE_STRUCTURAL_RISK")
            return report
        risk_distance = entry - structural_stop
        target = entry + PARENT_REWARD_RISK * risk_distance
        stressed_target = target * (Decimal(1) - STRESS_SLIP_PER_LEG)
        stressed_stop = structural_stop * (Decimal(1) - STRESS_SLIP_PER_LEG)
        net_target_per_unit = (
            stressed_target - entry
            - STRESS_FEE_PER_LEG * (entry + stressed_target)
        )
        net_stop_per_unit = (
            stressed_stop - entry
            - STRESS_FEE_PER_LEG * (entry + stressed_stop)
        )
        if not (net_target_per_unit > 0 and net_stop_per_unit < 0):
            report["reasons"].append("PROJECTED_STRESS_ECONOMICS_INVALID")
            return report
        report.update(
            study_eligible=True,
            decision_close_price=str(close),
            projected_next_open_entry_proxy=str(entry),
            structural_stop_price=str(structural_stop),
            projected_2r_target_price=str(target),
            projected_stress_target_net_per_unit=str(net_target_per_unit),
            projected_stress_stop_net_per_unit=str(net_stop_per_unit),
            structural_risk_in_prior_tr_mean=str(
                risk_distance / (sum(past_tr) / Decimal(14))
            ),
            next_open_fill_verified=False,
            future_target_or_stop_outcome_known=False,
        )
    return report
