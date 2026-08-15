from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from mean_reversion_walkforward_v1 import (
    MeanReversionWalkForwardError,
    WalkForwardConfig,
    _benchmark_targets,
    _warm_test_targets,
    run_mean_reversion_walk_forward,
)


def make_market(rows: int = 1800) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=rows, freq="4h", tz="UTC")
    closes = [100.0 + 0.01 * i + 7.0 * math.sin(i / 18.0) + 2.0 * math.sin(i / 5.0) for i in range(rows)]
    opens = [closes[0]] + closes[:-1]
    highs = [max(o, c) + 1.0 for o, c in zip(opens, closes)]
    lows = [min(o, c) - 1.0 for o, c in zip(opens, closes)]
    return pd.DataFrame({"timestamp": timestamps, "open": opens, "high": highs, "low": lows, "close": closes})


def config(seed: int = 17) -> WalkForwardConfig:
    return WalkForwardConfig(train_bars=600, test_bars=150, step_bars=150, bootstrap_samples=300, bootstrap_seed=seed)


def test_walk_forward_is_deterministic_non_overlapping_and_oos_only() -> None:
    first = run_mean_reversion_walk_forward(make_market(), config=config())
    second = run_mean_reversion_walk_forward(make_market(), config=config())
    assert first == second
    assert first["authority"] == "research-backtest-paper-only"
    assert first["automatic_promotion_allowed"] is False
    assert first["fold_start_state"].startswith("flat")
    assert len(first["folds"]) >= 3
    prior_end = None
    for fold in first["folds"]:
        train_end = pd.Timestamp(fold["train_end_utc"])
        test_start = pd.Timestamp(fold["test_start_utc"])
        test_end = pd.Timestamp(fold["test_end_utc"])
        assert train_end < test_start <= test_end
        if prior_end is not None:
            assert prior_end < test_start
        prior_end = test_end
        assert fold["selection_profile"] == "stress"
        assert set(fold["oos"]) == {"base", "stress"}


def test_future_prices_do_not_change_prior_fold_selection() -> None:
    original = make_market()
    changed = original.copy()
    cutoff = 1350
    changed.loc[changed.index >= cutoff, ["open", "high", "low", "close"]] *= 2.5
    before = run_mean_reversion_walk_forward(original, config=config(23))
    after = run_mean_reversion_walk_forward(changed, config=config(23))
    cutoff_timestamp = original.iloc[cutoff]["timestamp"]
    prior_before = [
        (fold["selected_lookback"], fold["selected_entry_z"], fold["selected_exit_z"])
        for fold in before["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < cutoff_timestamp
    ]
    prior_after = [
        (fold["selected_lookback"], fold["selected_entry_z"], fold["selected_exit_z"])
        for fold in after["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < cutoff_timestamp
    ]
    assert prior_before == prior_after


def test_warmup_does_not_carry_training_position_into_oos() -> None:
    frame = make_market(140)
    targets = _warm_test_targets(frame, test_start_offset=100, lookback=20, entry_z=-1.5, exit_z=-0.25)
    assert targets.iloc[:100].eq(0.0).all()


def test_buy_hold_benchmark_enters_exactly_at_first_oos_open() -> None:
    frame = make_market(130)
    offset = 100
    targets = _benchmark_targets(len(frame), offset)
    result = run_target_exposure_backtest(frame, targets, BacktestConfig(initial_cash=10_000.0, liquidate_at_end=True))
    first_fill = result.fills.iloc[0]
    assert first_fill["execution_time"] == frame.iloc[offset]["timestamp"]
    assert first_fill["signal_time"] == frame.iloc[offset - 1]["timestamp"]


def test_uncertainty_is_finite_and_fail_closed() -> None:
    result = run_mean_reversion_walk_forward(make_market(), config=config(31))
    for profile in ("base", "stress"):
        summary = result["uncertainty"][profile]
        interval = summary["median_excess_return_interval"]
        assert summary["fold_count"] >= 3
        assert 0.0 <= summary["positive_strategy_fraction"] <= 1.0
        assert 0.0 <= summary["positive_excess_fraction"] <= 1.0
        assert math.isfinite(float(interval["lower_95"]))
        assert math.isfinite(float(interval["upper_95"]))
        assert interval["lower_95"] <= interval["upper_95"]
    assert set(result["kill_conditions"]) == {
        "stress_no_positive_oos_excess_folds",
        "stress_median_excess_upper_bound_below_zero",
        "stress_majority_oos_returns_negative",
    }


def test_overlapping_oos_folds_fail_closed() -> None:
    with pytest.raises(MeanReversionWalkForwardError, match="do not overlap"):
        WalkForwardConfig(train_bars=600, test_bars=150, step_bars=100, bootstrap_samples=300)


def test_insufficient_rows_fail_closed() -> None:
    with pytest.raises(MeanReversionWalkForwardError, match="insufficient data"):
        run_mean_reversion_walk_forward(make_market(1000), config=config())


def test_duplicate_timestamps_fail_closed() -> None:
    market = make_market()
    market.loc[10, "timestamp"] = market.loc[9, "timestamp"]
    with pytest.raises(MeanReversionWalkForwardError, match="unique"):
        run_mean_reversion_walk_forward(market, config=config())
