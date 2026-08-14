from __future__ import annotations

import math

import pandas as pd
import pytest

from breakout_robustness_v1 import (
    BreakoutRobustnessError,
    build_breakout_targets,
    run_breakout_robustness,
)


def market_frame(rows: int = 180) -> pd.DataFrame:
    close = pd.Series([100.0 + index * 0.35 for index in range(rows)], dtype="float64")
    open_ = close.shift(1).fillna(close.iloc[0])
    high = pd.concat([open_, close], axis=1).max(axis=1) + 0.25
    low = pd.concat([open_, close], axis=1).min(axis=1) - 0.25
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2025-01-01", periods=rows, freq="4h", tz="UTC"),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
        }
    )


def test_breakout_uses_only_prior_range() -> None:
    frame = market_frame(80)
    original = build_breakout_targets(frame, 20, 10)

    modified = frame.copy()
    modified.loc[25, "high"] = modified.loc[25, "close"] + 10_000.0
    modified_target = build_breakout_targets(modified, 20, 10)

    assert original.iloc[25] == modified_target.iloc[25]
    assert original.iloc[25] == 1.0


def test_breakout_exit_persists_state_until_prior_low_break() -> None:
    frame = market_frame(80)
    targets = build_breakout_targets(frame, 20, 10)
    assert targets.iloc[25] == 1.0

    collapsed = frame.copy()
    prior_low = float(collapsed.loc[30:39, "low"].min())
    collapsed.loc[40, ["open", "high", "low", "close"]] = [
        prior_low - 1.0,
        prior_low - 0.5,
        prior_low - 1.5,
        prior_low - 1.0,
    ]
    collapsed_targets = build_breakout_targets(collapsed, 20, 10)
    assert collapsed_targets.iloc[39] == 1.0
    assert collapsed_targets.iloc[40] == 0.0


def test_invalid_ohlc_fails_closed() -> None:
    frame = market_frame(80)
    frame.loc[10, "close"] = frame.loc[10, "high"] + 1.0
    with pytest.raises(BreakoutRobustnessError, match="invalid OHLC"):
        build_breakout_targets(frame, 20, 10)


def test_robustness_returns_finite_research_evidence() -> None:
    result = run_breakout_robustness(market_frame())
    assert result["automatic_promotion_allowed"] is False
    assert result["authority"] == "research-backtest-paper-only"
    assert result["research_disposition"] in {
        "reject_hypothesis",
        "continue_to_walkforward_validation",
    }
    assert set(result["profile_summaries"]) == {"base", "stress"}
    assert len(result["runs"]) == 6
    for run in result["runs"]:
        assert math.isfinite(float(run["metric_total_return"]))
        assert math.isfinite(float(run["max_drawdown"]))


def test_window_contract_is_fail_closed() -> None:
    frame = market_frame(80)
    for entry_window, exit_window in [(10, 10), (5, 6), (2, 1)]:
        with pytest.raises(BreakoutRobustnessError):
            build_breakout_targets(frame, entry_window, exit_window)
