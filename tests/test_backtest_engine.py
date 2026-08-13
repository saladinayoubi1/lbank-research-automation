from __future__ import annotations

import math

import pandas as pd
import pytest

from backtest_engine import (
    BacktestConfig,
    BacktestError,
    run_target_exposure_backtest,
)


def make_market(
    opens: list[float],
    closes: list[float],
    *,
    start: str = "2025-01-01T00:00:00Z",
) -> pd.DataFrame:
    assert len(opens) == len(closes)
    timestamps = pd.date_range(start, periods=len(opens), freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": [max(open_, close) + 1 for open_, close in zip(opens, closes)],
            "low": [min(open_, close) - 1 for open_, close in zip(opens, closes)],
            "close": closes,
        }
    )


def test_zero_exposure_keeps_equity_flat() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 110, 90], [105, 95, 92]),
        [0, 0, 0],
        BacktestConfig(initial_cash=1_000),
    )

    assert result.fills.empty
    assert result.metrics["final_equity"] == pytest.approx(1_000)
    assert result.metrics["total_return"] == pytest.approx(0)
    assert result.metrics["max_drawdown"] == pytest.approx(0)


def test_signal_executes_at_next_candle_open() -> None:
    market = make_market([100, 110, 120], [105, 115, 125])
    result = run_target_exposure_backtest(
        market,
        [1, 1, 0],
        BacktestConfig(initial_cash=1_000),
    )

    first_fill = result.fills.iloc[0]
    assert first_fill["signal_time"] == market.iloc[0]["timestamp"]
    assert first_fill["execution_time"] == market.iloc[1]["timestamp"]
    assert first_fill["reference_price"] == pytest.approx(110)
    assert result.equity_curve.iloc[0]["position_quantity"] == pytest.approx(0)
    assert result.metrics["final_equity"] == pytest.approx(1_000 * 125 / 110)


def test_final_signal_is_ignored_without_a_next_candle() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100, 100], [100, 100, 100]),
        [0, 0, 1],
        BacktestConfig(initial_cash=1_000),
    )

    assert result.fills.empty
    assert result.metrics["final_equity"] == pytest.approx(1_000)


def test_long_position_profits_when_price_rises() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 110]),
        [1, 0],
        BacktestConfig(initial_cash=1_000),
    )

    assert result.metrics["final_equity"] == pytest.approx(1_100)
    assert list(result.fills["side"]) == ["buy", "sell"]


def test_short_position_profits_when_price_falls() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 90]),
        [-1, 0],
        BacktestConfig(initial_cash=1_000),
    )

    assert result.metrics["final_equity"] == pytest.approx(1_100)
    assert list(result.fills["side"]) == ["sell", "buy"]


def test_fees_are_charged_without_implicit_entry_leverage() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 100]),
        [1, 0],
        BacktestConfig(initial_cash=1_000, fee_bps=100),
    )

    entry = result.fills.iloc[0]
    assert entry["cash_after"] == pytest.approx(0)
    assert result.equity_curve.iloc[-1]["net_exposure"] == pytest.approx(0)
    assert result.metrics["total_fees"] == pytest.approx(19.801980198019802)
    assert result.metrics["final_equity"] == pytest.approx(980.1980198019802)


def test_slippage_is_adverse_without_implicit_entry_leverage() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 100]),
        [1, 0],
        BacktestConfig(initial_cash=1_000, slippage_bps=100),
    )

    entry = result.fills.iloc[0]
    assert entry["fill_price"] == pytest.approx(101)
    assert entry["cash_after"] == pytest.approx(0)
    assert result.fills.iloc[-1]["fill_price"] == pytest.approx(99)
    assert result.metrics["final_equity"] == pytest.approx(980.1980198019802)


def test_cost_aware_long_target_does_not_exceed_configured_exposure() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100, 100], [100, 100, 100]),
        [1, 1, 0],
        BacktestConfig(initial_cash=1_000, fee_bps=60, slippage_bps=20),
    )

    live_rows = result.equity_curve.iloc[:-1]
    assert (live_rows["net_exposure"].abs() <= 1.0 + 1e-12).all()
    assert result.fills.iloc[0]["cash_after"] >= -1e-9


def test_cost_aware_short_target_does_not_exceed_configured_exposure() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100, 100], [100, 100, 100]),
        [-1, -1, 0],
        BacktestConfig(initial_cash=1_000, fee_bps=60, slippage_bps=20),
    )

    live_rows = result.equity_curve.iloc[:-1]
    assert (live_rows["net_exposure"].abs() <= 1.0 + 1e-12).all()


def test_max_drawdown_is_reported_as_positive_magnitude() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 80]),
        [1, 0],
        BacktestConfig(initial_cash=1_000),
    )

    assert result.metrics["max_drawdown"] == pytest.approx(0.2)
    assert result.equity_curve.iloc[-1]["drawdown"] == pytest.approx(-0.2)


def test_open_position_can_remain_marked_to_market() -> None:
    result = run_target_exposure_backtest(
        make_market([100, 100], [100, 110]),
        [1, 0],
        BacktestConfig(initial_cash=1_000, liquidate_at_end=False),
    )

    assert len(result.fills) == 1
    assert result.equity_curve.iloc[-1]["position_quantity"] == pytest.approx(10)
    assert result.metrics["final_equity"] == pytest.approx(1_100)
    assert result.metrics["liquidated_at_end"] is False


def test_rejects_exposure_above_configured_limit() -> None:
    with pytest.raises(BacktestError, match="exceeds max_abs_exposure"):
        run_target_exposure_backtest(
            make_market([100, 100], [100, 100]),
            [1.01, 0],
            BacktestConfig(max_abs_exposure=1),
        )


def test_rejects_target_length_mismatch() -> None:
    with pytest.raises(BacktestError, match="length must equal"):
        run_target_exposure_backtest(
            make_market([100, 100], [100, 100]),
            [0],
        )


def test_rejects_non_finite_target() -> None:
    with pytest.raises(BacktestError, match="finite numbers"):
        run_target_exposure_backtest(
            make_market([100, 100], [100, 100]),
            [math.nan, 0],
        )


def test_rejects_duplicate_or_unsorted_timestamps() -> None:
    duplicate = make_market([100, 100], [100, 100])
    duplicate.loc[1, "timestamp"] = duplicate.loc[0, "timestamp"]
    with pytest.raises(BacktestError, match="unique"):
        run_target_exposure_backtest(duplicate, [0, 0])

    unsorted = make_market([100, 100], [100, 100]).iloc[::-1].reset_index(drop=True)
    with pytest.raises(BacktestError, match="sorted ascending"):
        run_target_exposure_backtest(unsorted, [0, 0])


def test_rejects_invalid_ohlc_relationships() -> None:
    market = make_market([100, 100], [100, 100])
    market.loc[0, "high"] = 99

    with pytest.raises(BacktestError, match="invalid OHLC"):
        run_target_exposure_backtest(market, [0, 0])


def test_config_rejects_invalid_costs_and_cash() -> None:
    with pytest.raises(BacktestError, match="initial_cash"):
        BacktestConfig(initial_cash=0)
    with pytest.raises(BacktestError, match="fee_bps"):
        BacktestConfig(fee_bps=-1)
    with pytest.raises(BacktestError, match="slippage_bps"):
        BacktestConfig(slippage_bps=-1)
