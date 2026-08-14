from __future__ import annotations

import pandas as pd
import pytest

from backtest_engine import BacktestError
from ema_trend_v1 import run_ema_trend_backtest, target_exposures


def make_market(closes: list[float]) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=len(closes), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [max(value - 1, 0.01) for value in closes],
            "close": closes,
        }
    )


def test_ema_v1_waits_for_slow_warmup() -> None:
    market = make_market([float(value) for value in range(1, 61)])
    targets = target_exposures(market)

    assert (targets.iloc[:49] == 0.0).all()
    assert targets.iloc[49] == pytest.approx(1.0)


def test_ema_v1_executes_first_eligible_signal_at_next_bar_open() -> None:
    market = make_market([float(value) for value in range(1, 61)])
    result = run_ema_trend_backtest(market, initial_cash=1_000.0)

    first_fill = result.fills.iloc[0]
    assert first_fill["signal_time"] == market.iloc[49]["timestamp"]
    assert first_fill["execution_time"] == market.iloc[50]["timestamp"]
    assert first_fill["reference_price"] == pytest.approx(market.iloc[50]["open"])


def test_ema_v1_stays_flat_in_monotonic_decline() -> None:
    market = make_market([float(value) for value in range(100, 40, -1)])
    result = run_ema_trend_backtest(market, initial_cash=1_000.0)

    assert result.fills.empty
    assert result.metrics["final_equity"] == pytest.approx(1_000.0)


def test_ema_v1_inherits_market_integrity_fail_closed() -> None:
    market = make_market([float(value) for value in range(1, 61)])
    market.loc[1, "timestamp"] = market.loc[0, "timestamp"]

    with pytest.raises(BacktestError, match="unique"):
        run_ema_trend_backtest(market)
