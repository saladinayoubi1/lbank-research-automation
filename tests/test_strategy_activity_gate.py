from datetime import datetime, timedelta, timezone

import pytest

from research.strategy_activity_gate import ActivityPolicy, evaluate_activity


UTC = timezone.utc


def dt(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def permissive_policy() -> ActivityPolicy:
    return ActivityPolicy(
        min_oos_trades=2,
        min_trades_per_30d=0.0,
        min_active_month_ratio=0.0,
        max_median_gap_days=365.0,
    )


def test_duplicate_timestamps_fail_closed() -> None:
    stamp = dt(2026, 1, 10)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_activity(
            [stamp, stamp],
            window_start=dt(2026, 1, 1),
            window_end=dt(2026, 2, 1),
            policy=permissive_policy(),
        )


def test_equivalent_instants_with_different_offsets_are_duplicates() -> None:
    plus_two = timezone(timedelta(hours=2))
    first = datetime(2026, 1, 10, 12, tzinfo=UTC)
    same_instant = datetime(2026, 1, 10, 14, tzinfo=plus_two)
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_activity(
            [first, same_instant],
            window_start=dt(2026, 1, 1),
            window_end=dt(2026, 2, 1),
            policy=permissive_policy(),
        )


def test_out_of_window_entry_fails_closed() -> None:
    with pytest.raises(ValueError, match="within"):
        evaluate_activity(
            [dt(2025, 12, 31, 23), dt(2026, 1, 10)],
            window_start=dt(2026, 1, 1),
            window_end=dt(2026, 2, 1),
            policy=permissive_policy(),
        )


def test_half_open_window_includes_start_and_excludes_end() -> None:
    result = evaluate_activity(
        [dt(2026, 1, 1), dt(2026, 1, 31, 23)],
        window_start=dt(2026, 1, 1),
        window_end=dt(2026, 2, 1),
        policy=permissive_policy(),
    )
    assert result.eligible
    assert result.trade_count == 2

    with pytest.raises(ValueError, match="within"):
        evaluate_activity(
            [dt(2026, 1, 10), dt(2026, 2, 1)],
            window_start=dt(2026, 1, 1),
            window_end=dt(2026, 2, 1),
            policy=permissive_policy(),
        )


def test_unsorted_input_is_evaluated_chronologically() -> None:
    result = evaluate_activity(
        [dt(2026, 1, 20), dt(2026, 1, 5), dt(2026, 1, 10)],
        window_start=dt(2026, 1, 1),
        window_end=dt(2026, 2, 1),
        policy=ActivityPolicy(
            min_oos_trades=3,
            min_trades_per_30d=0.0,
            min_active_month_ratio=0.0,
            max_median_gap_days=10.0,
        ),
    )
    assert result.eligible
    assert result.median_gap_days == 7.5


def test_naive_entry_and_window_timestamps_fail_closed() -> None:
    naive = datetime(2026, 1, 10)
    with pytest.raises(ValueError, match="entry_times"):
        evaluate_activity(
            [naive],
            window_start=dt(2026, 1, 1),
            window_end=dt(2026, 2, 1),
        )

    with pytest.raises(ValueError, match="window_start"):
        evaluate_activity(
            [dt(2026, 1, 10)],
            window_start=datetime(2026, 1, 1),
            window_end=dt(2026, 2, 1),
        )


def test_invalid_window_fails_closed() -> None:
    with pytest.raises(ValueError, match="after"):
        evaluate_activity(
            [],
            window_start=dt(2026, 2, 1),
            window_end=dt(2026, 2, 1),
        )


def test_duration_and_calendar_months_are_derived_from_window() -> None:
    policy = ActivityPolicy(
        min_oos_trades=2,
        min_trades_per_30d=1.9,
        min_active_month_ratio=1.0,
        max_median_gap_days=40.0,
    )
    result = evaluate_activity(
        [dt(2026, 1, 15), dt(2026, 2, 15)],
        window_start=dt(2026, 1, 1),
        window_end=dt(2026, 3, 1),
        policy=policy,
    )
    assert result.eligible
    assert result.active_month_ratio == 1.0
    assert result.trades_per_30d == pytest.approx(60.0 / 59.0)


def test_single_trade_candidate_remains_ineligible() -> None:
    result = evaluate_activity(
        [dt(2026, 1, 10)],
        window_start=dt(2026, 1, 1),
        window_end=dt(2026, 2, 1),
    )
    assert not result.eligible
    assert "INSUFFICIENT_OOS_TRADES" in result.reasons
    assert "TRADE_GAPS_TOO_WIDE" in result.reasons
