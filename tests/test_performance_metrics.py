from __future__ import annotations

import pandas as pd
import pytest

from performance_metrics import PerformanceMetricError, calculate_performance_metrics


def _curve(equity: list[float], *, freq: str = "4h") -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=len(equity), freq=freq, tz="UTC")
    series = pd.Series(equity, dtype="float64")
    drawdown = series / series.cummax() - 1.0
    return pd.DataFrame({"timestamp": timestamps, "equity": series, "drawdown": drawdown})


def test_metrics_use_elapsed_time_and_remain_finite() -> None:
    metrics = calculate_performance_metrics(_curve([100.0, 102.0, 101.0, 104.0, 103.0, 106.0]))

    assert metrics["elapsed_years"] > 0
    assert metrics["observations_per_year"] > 0
    assert metrics["annualized_volatility"] > 0
    assert metrics["sharpe_available"] is True
    assert metrics["sortino_available"] is True
    assert metrics["calmar_available"] is True
    assert metrics["cvar_5pct_return"] < 0
    assert metrics["metric_total_return"] == pytest.approx(0.06)


def test_zero_drawdown_marks_calmar_unavailable_instead_of_infinite() -> None:
    metrics = calculate_performance_metrics(_curve([100.0, 101.0, 102.0, 103.0]))

    assert metrics["calmar_available"] is False
    assert metrics["calmar"] == 0.0


def test_no_downside_marks_sortino_unavailable_instead_of_infinite() -> None:
    metrics = calculate_performance_metrics(_curve([100.0, 101.0, 102.0, 103.0]))

    assert metrics["sortino_available"] is False
    assert metrics["sortino"] == 0.0


def test_non_positive_equity_fails_closed() -> None:
    with pytest.raises(PerformanceMetricError, match="positive"):
        calculate_performance_metrics(_curve([100.0, 90.0, 0.0, 80.0]))


def test_duplicate_timestamp_fails_closed() -> None:
    frame = _curve([100.0, 101.0, 99.0])
    frame.loc[1, "timestamp"] = frame.loc[0, "timestamp"]
    with pytest.raises(PerformanceMetricError, match="unique"):
        calculate_performance_metrics(frame)
