from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from breakout_walkforward_v1 import (
    BreakoutWalkForwardError,
    WalkForwardConfig,
    _benchmark_targets,
    _warm_test_targets,
    run_breakout_walk_forward,
)


def make_market(rows: int = 1800) -> pd.DataFrame:
    timestamps = pd.date_range(
        "2024-01-01T00:00:00Z", periods=rows, freq="4h", tz="UTC"
    )
    closes = [
        100.0
        + 0.025 * index
        + 8.0 * math.sin(index / 22.0)
        + 2.5 * math.sin(index / 7.0)
        for index in range(rows)
    ]
    opens = [closes[0]] + closes[:-1]
    highs = [max(open_, close) + 1.0 for open_, close in zip(opens, closes)]
    lows = [min(open_, close) - 1.0 for open_, close in zip(opens, closes)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
        }
    )


def test_walk_forward_is_deterministic_non_overlapping_and_oos_only() -> None:
    config = WalkForwardConfig(
        train_bars=600,
        test_bars=150,
        step_bars=150,
        bootstrap_samples=300,
        bootstrap_seed=17,
    )
    first = run_breakout_walk_forward(make_market(), config=config)
    second = run_breakout_walk_forward(make_market(), config=config)

    assert first == second
    assert first["authority"] == "research-backtest-paper-only"
    assert first["automatic_promotion_allowed"] is False
    assert first["fold_start_state"].startswith("flat")
    assert len(first["folds"]) >= 3

    prior_test_end = None
    for fold in first["folds"]:
        train_end = pd.Timestamp(fold["train_end_utc"])
        test_start = pd.Timestamp(fold["test_start_utc"])
        test_end = pd.Timestamp(fold["test_end_utc"])
        assert train_end < test_start <= test_end
        if prior_test_end is not None:
            assert prior_test_end < test_start
        prior_test_end = test_end
        assert fold["selected_exit_window"] < fold["selected_entry_window"]
        assert fold["selection_profile"] == "stress"
        assert set(fold["oos"]) == {"base", "stress"}


def test_future_prices_do_not_change_prior_fold_selection() -> None:
    config = WalkForwardConfig(
        train_bars=600,
        test_bars=150,
        step_bars=150,
        bootstrap_samples=300,
        bootstrap_seed=23,
    )
    original = make_market()
    changed = original.copy()
    cutoff = 1350
    changed.loc[changed.index >= cutoff, ["open", "high", "low", "close"]] *= 3.0

    before = run_breakout_walk_forward(original, config=config)
    after = run_breakout_walk_forward(changed, config=config)

    cutoff_timestamp = original.iloc[cutoff]["timestamp"]
    prior_before = [
        (fold["selected_entry_window"], fold["selected_exit_window"])
        for fold in before["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < cutoff_timestamp
    ]
    prior_after = [
        (fold["selected_entry_window"], fold["selected_exit_window"])
        for fold in after["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < cutoff_timestamp
    ]
    assert prior_before == prior_after


def test_warmup_does_not_carry_training_position_into_oos() -> None:
    rows = 140
    timestamps = pd.date_range(
        "2024-01-01T00:00:00Z", periods=rows, freq="4h", tz="UTC"
    )
    closes = [100.0 + index for index in range(110)] + [209.0] * 30
    frame = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
        }
    )

    targets = _warm_test_targets(
        frame,
        test_start_offset=110,
        entry_window=20,
        exit_window=10,
    )

    assert targets.iloc[:110].eq(0.0).all()
    assert targets.iloc[110] == 0.0


def test_buy_hold_benchmark_enters_exactly_at_first_oos_open() -> None:
    frame = make_market(130)
    test_start_offset = 100
    targets = _benchmark_targets(len(frame), test_start_offset)

    result = run_target_exposure_backtest(
        frame,
        targets,
        BacktestConfig(initial_cash=10_000.0, liquidate_at_end=True),
    )

    first_fill = result.fills.iloc[0]
    assert first_fill["reason"] == "target_rebalance"
    assert first_fill["execution_time"] == frame.iloc[test_start_offset]["timestamp"]
    assert first_fill["signal_time"] == frame.iloc[test_start_offset - 1]["timestamp"]


def test_uncertainty_is_finite_and_fail_closed() -> None:
    result = run_breakout_walk_forward(
        make_market(),
        config=WalkForwardConfig(
            train_bars=600,
            test_bars=150,
            step_bars=150,
            bootstrap_samples=300,
            bootstrap_seed=31,
        ),
    )

    for profile in ("base", "stress"):
        summary = result["uncertainty"][profile]
        interval = summary["median_excess_return_interval"]
        assert summary["fold_count"] >= 3
        assert 0.0 <= summary["positive_strategy_fraction"] <= 1.0
        assert 0.0 <= summary["positive_excess_fraction"] <= 1.0
        assert math.isfinite(float(interval["median"]))
        assert math.isfinite(float(interval["lower_95"]))
        assert math.isfinite(float(interval["upper_95"]))
        assert interval["lower_95"] <= interval["upper_95"]

    assert set(result["kill_conditions"]) == {
        "stress_no_positive_oos_excess_folds",
        "stress_median_excess_upper_bound_below_zero",
        "stress_majority_oos_returns_negative",
    }


def test_overlapping_oos_folds_fail_closed() -> None:
    with pytest.raises(BreakoutWalkForwardError, match="do not overlap"):
        WalkForwardConfig(
            train_bars=600,
            test_bars=150,
            step_bars=100,
            bootstrap_samples=300,
        )


def test_insufficient_rows_fail_closed() -> None:
    with pytest.raises(BreakoutWalkForwardError, match="insufficient data"):
        run_breakout_walk_forward(
            make_market(1000),
            config=WalkForwardConfig(
                train_bars=600,
                test_bars=150,
                step_bars=150,
                bootstrap_samples=300,
            ),
        )


def test_duplicate_timestamps_fail_closed() -> None:
    market = make_market()
    market.loc[10, "timestamp"] = market.loc[9, "timestamp"]
    with pytest.raises(BreakoutWalkForwardError, match="unique"):
        run_breakout_walk_forward(
            market,
            config=WalkForwardConfig(
                train_bars=600,
                test_bars=150,
                step_bars=150,
                bootstrap_samples=300,
            ),
        )
