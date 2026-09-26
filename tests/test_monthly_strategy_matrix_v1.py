import numpy as np
import pandas as pd
import pytest

import nexus_monthly_strategy_matrix_v1 as matrix
from backtest_engine import BacktestConfig, run_target_exposure_backtest


def frame(count=700):
    rng = np.random.default_rng(481)
    close = 100*np.exp(np.cumsum(rng.normal(0.0002, 0.012, count)))
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-01", periods=count, freq="h", tz="UTC"),
        "open": close, "high": close*1.01, "low": close*.99, "close": close,
        "volume": rng.uniform(10, 100, count)})


@pytest.mark.parametrize("strategy", matrix.STRATEGIES)
def test_signals_are_causal_and_binary(strategy):
    data = frame()
    original = matrix.targets(data, strategy)
    changed = data.copy()
    changed.loc[600:, ["open", "high", "low", "close"]] *= 7
    pd.testing.assert_series_equal(original.iloc[:600], matrix.targets(changed, strategy).iloc[:600])
    pd.testing.assert_series_equal(original.iloc[:600], matrix.targets(data.iloc[:600], strategy))
    assert set(original.unique()) <= {0.0, 1.0}


@pytest.mark.parametrize("strategy", matrix.STRATEGIES)
def test_realized_ledger_reconciles_with_equity(strategy):
    data = frame()
    result = run_target_exposure_backtest(data, matrix.targets(data, strategy),
        BacktestConfig(initial_cash=500, fee_bps=25, slippage_bps=15))
    report = matrix.summarize(result)
    assert report["entries"] == report["completed_trades"] == report["exits"]
    assert report["wins"]+report["losses"]+report["breakeven"] == report["completed_trades"]
    assert report["gross_winning_net_trades"]+report["gross_losing_net_trades"] == pytest.approx(report["net_pnl"])
    assert result.equity_curve.cash.min() >= -1e-8
    matrix.digest(report)


def test_low_activity_is_reported_without_a_four_fill_gate():
    data = frame(40)
    data[["open", "high", "low", "close"]] = 100.0
    result = run_target_exposure_backtest(data, [1.0]*40,
        BacktestConfig(initial_cash=500, fee_bps=10, slippage_bps=5))
    report = matrix.summarize(result)
    assert report["fill_count"] == 2
    assert report["completed_trades"] == 1
    assert report["losses"] == 1
    assert report["net_pnl"] < 0
    assert matrix.CONTRACT["per_strategy_minimum_trades_gate"] is None
    assert result.fills.iloc[0].execution_time > result.fills.iloc[0].signal_time


def test_empty_activity_is_not_a_profitable_strategy():
    result = run_target_exposure_backtest(frame(30), [0.0]*30, BacktestConfig(initial_cash=500))
    report = matrix.summarize(result)
    assert report["completed_trades"] == report["wins"] == report["losses"] == 0
    assert report["net_pnl"] == 0
    assert matrix.CONTRACT["automatic_promotion"] is False
