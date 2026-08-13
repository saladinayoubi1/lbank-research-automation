"""Deterministic EMA(20,50) research strategy for Phase 3 validation.

Research/backtest/paper-only. Signals use completed-bar closes; execution lag and
cost accounting are owned by ``backtest_engine.run_target_exposure_backtest``.
"""
from __future__ import annotations

import pandas as pd

from backtest_engine import BacktestConfig, BacktestResult, run_target_exposure_backtest

FAST_SPAN = 20
SLOW_SPAN = 50


class EmaTrendError(RuntimeError):
    pass


def target_exposures(market_frame: pd.DataFrame) -> pd.Series:
    if "close" not in market_frame:
        raise EmaTrendError("market frame is missing close")
    close = pd.to_numeric(market_frame["close"], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise EmaTrendError("close must contain positive numeric values")

    fast = close.ewm(span=FAST_SPAN, adjust=False, min_periods=FAST_SPAN).mean()
    slow = close.ewm(span=SLOW_SPAN, adjust=False, min_periods=SLOW_SPAN).mean()
    eligible = fast.notna() & slow.notna()
    targets = ((fast > slow) & eligible).astype("float64")
    targets.name = "target_exposure"
    return targets


def run_ema_trend_backtest(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float = 10_000.0,
    fee_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> BacktestResult:
    config = BacktestConfig(
        initial_cash=initial_cash,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        max_abs_exposure=1.0,
        liquidate_at_end=True,
    )
    return run_target_exposure_backtest(
        market_frame,
        target_exposures(market_frame),
        config,
    )
