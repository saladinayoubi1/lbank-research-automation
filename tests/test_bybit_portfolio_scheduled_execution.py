from __future__ import annotations

import numpy as np
import pandas as pd

from bybit_portfolio_search_v3_scheduled import exact_backtest


def test_constant_target_is_not_rebalanced_every_bar() -> None:
    timestamps = pd.date_range("2024-01-01", periods=20, freq="4h", tz="UTC")
    prices = np.column_stack([
        np.linspace(100.0, 110.0, len(timestamps)),
        np.linspace(200.0, 202.0, len(timestamps)),
    ])
    market = {
        "timestamps": pd.Series(timestamps),
        "open": prices.copy(),
        "close": prices.copy(),
        "high": prices * 1.01,
        "low": prices * 0.99,
        "symbols": ["btc_usdt", "eth_usdt"],
    }
    weights = np.zeros((len(timestamps), 2))
    weights[:, 0] = 0.5
    result = exact_backtest(
        market,
        weights,
        {"start": "2024-01-01", "end": "2024-02-01"},
        {"initial_cash": 10000.0, "fee_bps": 10.0, "slippage_bps": 5.0},
    )
    assert result["asset_fill_counts"] == [2, 0]
    assert result["fill_count"] == 2
