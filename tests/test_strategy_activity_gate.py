from datetime import datetime, timedelta, timezone

import pytest

from research.strategy_activity_gate import ActivityPolicy, evaluate_activity


UTC = timezone.utc


def _monthly_entries(count: int, *, start: datetime = datetime(2026, 1, 1, tzinfo=UTC)):
    return [start + timedelta(days=5 * i) for i in range(count)]


def test_activity_gate_accepts_sufficiently_active_oos_candidate():
    entries = _monthly_entries(40)

    result = evaluate_activity(
        entries,
        evaluation_days=200,
        total_calendar_months=7,
    )

    assert result.eligible is True
    assert result.reasons == ()
    assert result.trade_count == 40
    assert result.trades_per_30d == pytest.approx(6.0)
    assert result.median_gap_days == pytest.approx(5.0)


def test_activity_gate_rejects_sparse_candidate_for_each_default_dimension():
    entries = [
        datetime(2026, 1, 1, tzinfo=UTC),
        datetime(2026, 2, 20, tzinfo=UTC),
        datetime(2026, 4, 20, tzinfo=UTC),
    ]

    result = evaluate_activity(
        entries,
        evaluation_days=180,
        total_calendar_months=6,
    )

    assert result.eligible is False
    assert set(result.reasons) == {
        "INSUFFICIENT_OOS_TRADES",
        "SIGNAL_FREQUENCY_TOO_LOW",
        "TOO_FEW_ACTIVE_MONTHS",
        "TRADE_GAPS_TOO_WIDE",
    }


def test_activity_gate_rejects_naive_timestamps():
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_activity(
            [datetime(2026, 1, 1)],
            evaluation_days=30,
            total_calendar_months=1,
        )


def test_activity_gate_rejects_invalid_evaluation_window():
    with pytest.raises(ValueError, match="evaluation_days"):
        evaluate_activity([], evaluation_days=0, total_calendar_months=1)

    with pytest.raises(ValueError, match="total_calendar_months"):
        evaluate_activity([], evaluation_days=30, total_calendar_months=0)


def test_custom_policy_is_applied_deterministically():
    entries = _monthly_entries(5)
    policy = ActivityPolicy(
        min_oos_trades=5,
        min_trades_per_30d=1.0,
        min_active_month_ratio=0.1,
        max_median_gap_days=6.0,
    )

    result = evaluate_activity(
        entries,
        evaluation_days=30,
        total_calendar_months=2,
        policy=policy,
    )

    assert result.eligible is True
    assert result.reasons == ()
