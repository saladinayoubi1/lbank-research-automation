from __future__ import annotations

from math import isfinite, sqrt
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from performance_metrics import calculate_performance_metrics

# Preregistered before observing strategy results.
# Each tuple is (momentum lookback bars, volatility lookback bars, entry score, exit score).
PARAMETER_GRID = (
    (24, 24, 1.0, 0.0),
    (48, 48, 1.25, 0.0),
    (96, 96, 1.5, 0.25),
)
EXECUTION_PROFILES = {
    "base": {"fee_bps": 10.0, "slippage_bps": 5.0},
    "stress": {"fee_bps": 20.0, "slippage_bps": 10.0},
}


class VolAdjustedMomentumError(RuntimeError):
    pass


def _validated_ohlc(market_frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(market_frame.columns))
    if missing:
        raise VolAdjustedMomentumError(f"market frame is missing columns: {missing}")

    frame = market_frame.loc[:, ["timestamp", "open", "high", "low", "close"]].copy()
    try:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    except (TypeError, ValueError) as exc:
        raise VolAdjustedMomentumError("timestamps must be valid UTC-compatible values") from exc
    if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise VolAdjustedMomentumError("timestamps must be unique and sorted ascending")

    numeric = frame.loc[:, ["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise VolAdjustedMomentumError("OHLC must be numeric")
    if not numeric.map(lambda value: isfinite(float(value))).all().all():
        raise VolAdjustedMomentumError("OHLC must be finite")
    if (numeric <= 0).any().any():
        raise VolAdjustedMomentumError("OHLC must be positive")
    if (
        (numeric["high"] < numeric["low"])
        | (numeric["open"] > numeric["high"])
        | (numeric["open"] < numeric["low"])
        | (numeric["close"] > numeric["high"])
        | (numeric["close"] < numeric["low"])
    ).any():
        raise VolAdjustedMomentumError("market frame contains invalid OHLC relationships")
    frame.loc[:, ["open", "high", "low", "close"]] = numeric
    return frame


def build_vol_adjusted_momentum_targets(
    market_frame: pd.DataFrame,
    momentum_lookback: int,
    volatility_lookback: int,
    entry_score: float,
    exit_score: float,
) -> pd.Series:
    """Long-only volatility-adjusted time-series momentum on completed bars.

    score[t] = log(close[t] / close[t-L]) / (sigma_t * sqrt(L)), where sigma_t is
    the rolling standard deviation of one-bar log returns. The target decided at t
    is executed by the shared engine at open[t+1].
    """
    if not isinstance(momentum_lookback, int) or momentum_lookback < 8:
        raise VolAdjustedMomentumError("momentum_lookback must be an integer >= 8")
    if not isinstance(volatility_lookback, int) or volatility_lookback < 8:
        raise VolAdjustedMomentumError("volatility_lookback must be an integer >= 8")
    if not isfinite(float(entry_score)) or not isfinite(float(exit_score)):
        raise VolAdjustedMomentumError("score thresholds must be finite")
    if entry_score <= 0.0 or exit_score >= entry_score:
        raise VolAdjustedMomentumError("entry_score must be positive and above exit_score")

    frame = _validated_ohlc(market_frame)
    close = frame["close"].astype("float64")
    log_close = close.map(lambda value: __import__("math").log(float(value)))
    log_returns = log_close.diff()
    realized_vol = log_returns.rolling(
        volatility_lookback,
        min_periods=volatility_lookback,
    ).std(ddof=0)
    raw_momentum = log_close - log_close.shift(momentum_lookback)
    denominator = realized_vol * sqrt(float(momentum_lookback))
    score = raw_momentum / denominator.replace(0.0, float("nan"))

    in_position = False
    values: list[float] = []
    for idx in range(len(frame)):
        current = score.iloc[idx]
        if pd.notna(current) and isfinite(float(current)):
            if in_position and float(current) <= exit_score:
                in_position = False
            elif not in_position and float(current) >= entry_score:
                in_position = True
        values.append(1.0 if in_position else 0.0)

    return pd.Series(values, index=market_frame.index, dtype="float64", name="target_exposure")


def _backtest(
    market_frame: pd.DataFrame,
    targets: pd.Series,
    *,
    initial_cash: float,
    fee_bps: float,
    slippage_bps: float,
) -> dict[str, float | int | bool]:
    result = run_target_exposure_backtest(
        market_frame,
        targets,
        BacktestConfig(
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_abs_exposure=1.0,
            liquidate_at_end=True,
        ),
    )
    metrics = {**result.metrics, **calculate_performance_metrics(result.equity_curve)}
    cleaned: dict[str, float | int | bool] = {}
    for key, value in metrics.items():
        if isinstance(value, bool):
            cleaned[key] = value
            continue
        numeric = float(value)
        if not isfinite(numeric):
            raise VolAdjustedMomentumError(f"metric became non-finite: {key}")
        cleaned[key] = int(value) if isinstance(value, int) else numeric
    return cleaned


def _buy_hold_total_return(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float,
    fee_bps: float,
    slippage_bps: float,
) -> float:
    frame = _validated_ohlc(market_frame)
    if len(frame) < 2:
        raise VolAdjustedMomentumError("Buy & Hold benchmark needs at least two bars")

    first_open = float(frame.iloc[0]["open"])
    last_close = float(frame.iloc[-1]["close"])
    first_timestamp = frame.iloc[0]["timestamp"]
    last_timestamp = frame.iloc[-1]["timestamp"]
    low = min(first_open, last_close)
    high = max(first_open, last_close)
    execution_frame = pd.DataFrame(
        {
            "timestamp": [first_timestamp - pd.Timedelta(nanoseconds=1), last_timestamp],
            "open": [first_open, first_open],
            "high": [first_open, high],
            "low": [first_open, low],
            "close": [first_open, last_close],
        }
    )
    result = run_target_exposure_backtest(
        execution_frame,
        pd.Series([1.0, 1.0], dtype="float64"),
        BacktestConfig(
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_abs_exposure=1.0,
            liquidate_at_end=True,
        ),
    )
    total_return = float(result.metrics["total_return"])
    if not isfinite(total_return):
        raise VolAdjustedMomentumError("Buy & Hold benchmark became non-finite")
    return total_return


def run_vol_adjusted_momentum_robustness(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    if initial_cash <= 0 or not isfinite(float(initial_cash)):
        raise VolAdjustedMomentumError("initial_cash must be finite and positive")
    _validated_ohlc(market_frame)

    runs: list[dict[str, object]] = []
    summaries: dict[str, object] = {}
    for profile_id, profile in EXECUTION_PROFILES.items():
        fee_bps = float(profile["fee_bps"])
        slippage_bps = float(profile["slippage_bps"])
        benchmark_return = _buy_hold_total_return(
            market_frame,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        profile_runs: list[dict[str, object]] = []
        for momentum_lookback, volatility_lookback, entry_score, exit_score in PARAMETER_GRID:
            metrics = _backtest(
                market_frame,
                build_vol_adjusted_momentum_targets(
                    market_frame,
                    momentum_lookback,
                    volatility_lookback,
                    entry_score,
                    exit_score,
                ),
                initial_cash=initial_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            total_return = float(metrics["metric_total_return"])
            row = {
                "profile_id": profile_id,
                "momentum_lookback": momentum_lookback,
                "volatility_lookback": volatility_lookback,
                "entry_score": entry_score,
                "exit_score": exit_score,
                "benchmark_total_return": benchmark_return,
                "excess_return_vs_buy_hold": total_return - benchmark_return,
                **metrics,
            }
            profile_runs.append(row)
            runs.append(row)

        returns = [float(item["metric_total_return"]) for item in profile_runs]
        excess = [float(item["excess_return_vs_buy_hold"]) for item in profile_runs]
        fills = [int(float(item.get("fill_count", 0))) for item in profile_runs]
        summaries[profile_id] = {
            "benchmark_total_return": benchmark_return,
            "median_total_return": median(returns),
            "worst_total_return": min(returns),
            "best_total_return": max(returns),
            "median_excess_return_vs_buy_hold": median(excess),
            "positive_return_fraction": sum(value > 0.0 for value in returns) / len(returns),
            "positive_excess_fraction": sum(value > 0.0 for value in excess) / len(excess),
            "all_variants_inactive": all(value == 0 for value in fills),
        }

    stress = summaries["stress"]
    kill_conditions = {
        "all_stress_variants_inactive": bool(stress["all_variants_inactive"]),
        "all_stress_variants_negative": float(stress["best_total_return"]) < 0.0,
        "all_stress_variants_trail_buy_hold": float(stress["positive_excess_fraction"]) == 0.0,
    }
    disposition = (
        "reject_hypothesis"
        if any(kill_conditions.values())
        else "continue_to_walkforward_validation"
    )
    return {
        "schema_version": 1,
        "hypothesis": "long-only volatility-adjusted time-series momentum on completed 4h bars",
        "parameter_grid": [
            {
                "momentum_lookback": momentum_lookback,
                "volatility_lookback": volatility_lookback,
                "entry_score": entry_score,
                "exit_score": exit_score,
            }
            for momentum_lookback, volatility_lookback, entry_score, exit_score in PARAMETER_GRID
        ],
        "execution_profiles": EXECUTION_PROFILES,
        "runs": runs,
        "profile_summaries": summaries,
        "kill_conditions": kill_conditions,
        "research_disposition": disposition,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
