from __future__ import annotations

import math

import pandas as pd
import pytest

from ema_walkforward_v1 import EmaWalkForwardError, WalkForwardConfig, run_ema_walk_forward


def make_market(rows: int = 900) -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01T00:00:00Z", periods=rows, freq="4h", tz="UTC")
    closes = [
        100.0
        + 0.03 * index
        + 7.0 * math.sin(index / 18.0)
        + 2.0 * math.sin(index / 5.0)
        for index in range(rows)
    ]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1.0 for value in closes],
            "low": [value - 1.0 for value in closes],
            "close": closes,
        }
    )


def test_walk_forward_is_deterministic_and_oos_only() -> None:
    market = make_market()
    config = WalkForwardConfig(
        train_bars=300,
        test_bars=100,
        step_bars=100,
        bootstrap_samples=400,
        bootstrap_seed=17,
    )
    first = run_ema_walk_forward(market, config=config)
    second = run_ema_walk_forward(market, config=config)

    assert first == second
    assert first["authority"] == "research-backtest-paper-only"
    assert first["automatic_promotion_allowed"] is False
    assert len(first["folds"]) == 6

    for fold in first["folds"]:
        assert pd.Timestamp(fold["train_end_utc"]) < pd.Timestamp(fold["test_start_utc"])
        assert fold["selected_fast_span"] < fold["selected_slow_span"]
        assert fold["selection_profile"] == "stress"
        assert set(fold["oos"]) == {"base", "stress"}


def test_future_prices_do_not_change_prior_fold_selection() -> None:
    config = WalkForwardConfig(
        train_bars=300,
        test_bars=100,
        step_bars=100,
        bootstrap_samples=300,
        bootstrap_seed=23,
    )
    original = make_market()
    changed = original.copy()
    changed.loc[changed.index >= 700, ["open", "high", "low", "close"]] *= 3.0

    before = run_ema_walk_forward(original, config=config)
    after = run_ema_walk_forward(changed, config=config)

    prior_before = [
        (fold["selected_fast_span"], fold["selected_slow_span"])
        for fold in before["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < original.iloc[700]["timestamp"]
    ]
    prior_after = [
        (fold["selected_fast_span"], fold["selected_slow_span"])
        for fold in after["folds"]
        if pd.Timestamp(fold["train_end_utc"]) < original.iloc[700]["timestamp"]
    ]
    assert prior_before == prior_after


def test_uncertainty_is_finite_and_fail_closed() -> None:
    result = run_ema_walk_forward(
        make_market(),
        config=WalkForwardConfig(
            train_bars=300,
            test_bars=100,
            step_bars=100,
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


def test_insufficient_rows_fail_closed() -> None:
    with pytest.raises(EmaWalkForwardError, match="insufficient data"):
        run_ema_walk_forward(
            make_market(520),
            config=WalkForwardConfig(
                train_bars=300,
                test_bars=100,
                step_bars=100,
                bootstrap_samples=300,
            ),
        )


def test_duplicate_timestamps_fail_closed() -> None:
    market = make_market()
    market.loc[10, "timestamp"] = market.loc[9, "timestamp"]
    with pytest.raises(EmaWalkForwardError, match="unique"):
        run_ema_walk_forward(
            market,
            config=WalkForwardConfig(
                train_bars=300,
                test_bars=100,
                step_bars=100,
                bootstrap_samples=300,
            ),
        )
