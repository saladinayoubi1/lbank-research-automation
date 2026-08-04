from __future__ import annotations

import numpy as np
import pandas as pd

from bybit_long_short_search_v4 import approximate_backtest, gate_checks, summarize


def market() -> dict[str, object]:
    timestamps = pd.date_range("2024-01-01", periods=60, freq="4h", tz="UTC")
    btc = np.linspace(100.0, 80.0, len(timestamps))
    eth = np.linspace(100.0, 102.0, len(timestamps))
    close = np.column_stack([btc, eth])
    return {
        "timestamps": pd.Series(timestamps),
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "symbols": ["btc_usdt", "eth_usdt"],
    }


def test_short_position_profits_after_conservative_carry() -> None:
    data = market()
    weights = np.zeros((60, 2))
    weights[:, 0] = -0.5
    result = approximate_backtest(
        data,
        weights,
        {"start": "2024-01-01", "end": "2024-02-01"},
        {"initial_cash": 10000.0, "fee_bps": 10.0, "slippage_bps": 5.0, "annual_short_carry": 0.20},
    )
    assert result["total_return"] > 0
    assert result["asset_fill_counts"][0] >= 1


def test_dual_profile_gate_shape() -> None:
    rows = [
        {"total_return": 0.08, "max_drawdown": 0.10, "sharpe": 0.9, "fill_count": 6, "asset_fill_counts": [2, 2], "turnover": 3.0},
        {"total_return": 0.05, "max_drawdown": 0.12, "sharpe": 0.6, "fill_count": 8, "asset_fill_counts": [3, 3], "turnover": 4.0},
    ]
    summary = summarize(rows)
    gate = {
        "minimum_positive_ratio": 1.0,
        "minimum_median_return": 0.04,
        "minimum_worst_return": 0.0,
        "maximum_drawdown": 0.20,
        "minimum_median_sharpe": 0.5,
        "minimum_sharpe": 0.0,
        "minimum_fill_count": 4,
        "minimum_asset_fill_count": 1,
    }
    assert all(gate_checks(summary, gate).values())
