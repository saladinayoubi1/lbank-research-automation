from __future__ import annotations

import numpy as np
import pandas as pd

from bybit_portfolio_search_v3 import (
    approximate_backtest,
    development_checks,
    stress_checks,
    summarize,
)


def market() -> dict[str, object]:
    timestamps = pd.date_range("2024-01-01", periods=60, freq="4h", tz="UTC")
    btc = np.linspace(100.0, 130.0, len(timestamps))
    eth = np.linspace(100.0, 105.0, len(timestamps))
    close = np.column_stack([btc, eth])
    return {
        "timestamps": pd.Series(timestamps),
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "symbols": ["btc_usdt", "eth_usdt"],
    }


def test_portfolio_approximation_is_positive_on_rising_asset() -> None:
    data = market()
    weights = np.zeros((60, 2))
    weights[:, 0] = 1.0
    result = approximate_backtest(
        data,
        weights,
        {"start": "2024-01-01", "end": "2024-02-01"},
        cost_bps=0.0,
    )
    assert result["total_return"] > 0
    assert result["max_drawdown"] == 0
    assert result["asset_fill_counts"][0] >= 1


def test_development_and_stress_gates() -> None:
    rows = [
        {"total_return": 0.10, "max_drawdown": 0.08, "sharpe": 1.0, "fill_count": 4, "turnover": 2.0},
        {"total_return": 0.06, "max_drawdown": 0.10, "sharpe": 0.7, "fill_count": 5, "turnover": 3.0},
    ]
    summary = summarize(rows)
    dev_gate = {
        "minimum_positive_ratio": 1.0,
        "minimum_median_return": 0.05,
        "minimum_worst_return": 0.0,
        "maximum_drawdown": 0.20,
        "minimum_median_sharpe": 0.5,
        "minimum_sharpe": 0.0,
        "minimum_fill_count": 2,
    }
    assert all(development_checks(summary, dev_gate).values())
    stress_gate = {
        "minimum_total_return": 0.02,
        "maximum_drawdown": 0.20,
        "minimum_sharpe": 0.25,
        "minimum_fill_count": 4,
        "minimum_asset_fill_count": 1,
    }
    stress_result = {
        "total_return": 0.05,
        "max_drawdown": 0.10,
        "sharpe": 0.8,
        "fill_count": 6,
        "asset_fill_counts": [2, 4],
    }
    assert all(stress_checks(stress_result, stress_gate).values())
