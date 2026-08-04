from __future__ import annotations

import numpy as np
import pandas as pd

from bybit_strategy_search_v2 import approx, checks, summarize


def _frame() -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=50, freq="4h", tz="UTC")
    close = np.linspace(100.0, 120.0, len(timestamps))
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1.0,
            "symbol": "btc_usdt",
            "timeframe": "hour4",
        }
    )


def test_approx_positive_for_rising_market() -> None:
    frame = _frame()
    targets = pd.Series(1.0, index=frame.index)
    result = approx(
        frame,
        targets,
        {"start": "2024-01-01", "end": "2024-02-01"},
        cost_bps=0.0,
    )
    assert result["total_return"] > 0
    assert result["max_drawdown"] == 0


def test_summary_and_gate_are_deterministic() -> None:
    rows = [
        {"total_return": 0.10, "max_drawdown": 0.08, "sharpe": 1.0, "fill_count": 3, "turnover": 2.0},
        {"total_return": 0.05, "max_drawdown": 0.10, "sharpe": 0.7, "fill_count": 4, "turnover": 3.0},
    ]
    summary = summarize(rows)
    gate = {
        "minimum_positive_ratio": 1.0,
        "minimum_median_return": 0.05,
        "minimum_worst_return": 0.0,
        "maximum_drawdown": 0.20,
        "minimum_median_sharpe": 0.5,
        "minimum_sharpe": 0.0,
        "minimum_fill_count": 2,
    }
    assert all(checks(summary, gate).values())
