from __future__ import annotations

from math import isfinite, sqrt

import pandas as pd

SECONDS_PER_YEAR = 365.25 * 24 * 60 * 60


class PerformanceMetricError(RuntimeError):
    pass


def calculate_performance_metrics(equity_curve: pd.DataFrame) -> dict[str, float | bool]:
    """Calculate bounded, finite research metrics from a marked-to-market equity curve.

    Annualization uses actual elapsed UTC time rather than assuming a fixed bar count,
    so missing observations cannot silently inflate Sharpe/Sortino. Undefined ratios
    are returned as 0.0 together with an explicit availability flag.
    """
    required = {"timestamp", "equity", "drawdown"}
    missing = sorted(required - set(equity_curve.columns))
    if missing:
        raise PerformanceMetricError(f"equity curve is missing columns: {missing}")
    if len(equity_curve) < 2:
        raise PerformanceMetricError("equity curve requires at least two observations")

    frame = equity_curve.loc[:, ["timestamp", "equity", "drawdown"]].copy()
    try:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    except (TypeError, ValueError) as exc:
        raise PerformanceMetricError("equity curve contains an invalid timestamp") from exc

    if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise PerformanceMetricError("equity timestamps must be unique and sorted ascending")

    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame["drawdown"] = pd.to_numeric(frame["drawdown"], errors="coerce")
    if frame[["equity", "drawdown"]].isna().any().any():
        raise PerformanceMetricError("equity curve contains non-numeric values")
    if not frame["equity"].map(lambda value: isfinite(float(value))).all():
        raise PerformanceMetricError("equity curve contains non-finite equity")
    if not frame["drawdown"].map(lambda value: isfinite(float(value))).all():
        raise PerformanceMetricError("equity curve contains non-finite drawdown")
    if (frame["equity"] <= 0).any():
        raise PerformanceMetricError("equity must remain positive for risk-adjusted metrics")

    elapsed_seconds = (frame.iloc[-1]["timestamp"] - frame.iloc[0]["timestamp"]).total_seconds()
    if elapsed_seconds <= 0:
        raise PerformanceMetricError("equity curve must span positive elapsed time")
    elapsed_years = elapsed_seconds / SECONDS_PER_YEAR

    returns = frame["equity"].pct_change().dropna()
    if returns.empty or not returns.map(lambda value: isfinite(float(value))).all():
        raise PerformanceMetricError("equity returns are unavailable or non-finite")

    observations_per_year = float(len(returns)) / elapsed_years
    total_return = float(frame.iloc[-1]["equity"] / frame.iloc[0]["equity"] - 1.0)
    annualized_return = float((frame.iloc[-1]["equity"] / frame.iloc[0]["equity"]) ** (1.0 / elapsed_years) - 1.0)

    mean_return = float(returns.mean())
    return_std = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    sharpe_available = len(returns) > 1 and return_std > 0.0
    sharpe = float(sqrt(observations_per_year) * mean_return / return_std) if sharpe_available else 0.0

    downside = returns[returns < 0]
    downside_std = float(downside.std(ddof=1)) if len(downside) > 1 else 0.0
    sortino_available = len(downside) > 1 and downside_std > 0.0
    sortino = float(sqrt(observations_per_year) * mean_return / downside_std) if sortino_available else 0.0

    max_drawdown = float(max(0.0, -frame["drawdown"].min()))
    calmar_available = max_drawdown > 0.0
    calmar = float(annualized_return / max_drawdown) if calmar_available else 0.0

    quantile_5 = float(returns.quantile(0.05))
    lower_tail = returns[returns <= quantile_5]
    cvar_5pct_return = float(lower_tail.mean()) if not lower_tail.empty else quantile_5

    metrics = {
        "elapsed_years": float(elapsed_years),
        "observations_per_year": observations_per_year,
        "annualized_return": annualized_return,
        "annualized_volatility": float(return_std * sqrt(observations_per_year)),
        "sharpe": sharpe,
        "sharpe_available": sharpe_available,
        "sortino": sortino,
        "sortino_available": sortino_available,
        "calmar": calmar,
        "calmar_available": calmar_available,
        "cvar_5pct_return": cvar_5pct_return,
        "metric_total_return": total_return,
    }
    for name, value in metrics.items():
        if isinstance(value, bool):
            continue
        if not isfinite(float(value)):
            raise PerformanceMetricError(f"metric became non-finite: {name}")
    return metrics
