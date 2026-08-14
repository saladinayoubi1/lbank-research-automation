from __future__ import annotations

from math import isfinite
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from performance_metrics import calculate_performance_metrics

# Preregistered before seeing strategy results. Each tuple is
# (lookback bars, entry z-score, exit z-score).
PARAMETER_GRID = (
    (20, -1.5, -0.25),
    (48, -2.0, 0.0),
    (96, -2.5, 0.0),
)
EXECUTION_PROFILES = {
    "base": {"fee_bps": 10.0, "slippage_bps": 5.0},
    "stress": {"fee_bps": 20.0, "slippage_bps": 10.0},
}


class MeanReversionRobustnessError(RuntimeError):
    pass


def build_mean_reversion_targets(
    market_frame: pd.DataFrame,
    lookback: int,
    entry_z: float,
    exit_z: float,
) -> pd.Series:
    """Long-only close-to-mean reversion using completed bars only.

    The signal at bar t may change target exposure using bar-t close history, while
    the shared backtest engine executes that target at bar t+1 open.
    """
    if not isinstance(lookback, int) or lookback < 10:
        raise MeanReversionRobustnessError("lookback must be an integer >= 10")
    if not isfinite(float(entry_z)) or not isfinite(float(exit_z)):
        raise MeanReversionRobustnessError("z-score thresholds must be finite")
    if entry_z >= exit_z or entry_z >= 0.0:
        raise MeanReversionRobustnessError(
            "entry_z must be negative and strictly below exit_z"
        )

    required = {"open", "high", "low", "close"}
    missing = sorted(required - set(market_frame.columns))
    if missing:
        raise MeanReversionRobustnessError(f"market frame is missing columns: {missing}")

    frame = market_frame.loc[:, ["open", "high", "low", "close"]].apply(
        pd.to_numeric, errors="coerce"
    )
    if frame.isna().any().any():
        raise MeanReversionRobustnessError("OHLC must be numeric")
    if (frame <= 0).any().any():
        raise MeanReversionRobustnessError("OHLC must be positive")
    if (
        (frame["high"] < frame["low"])
        | (frame["open"] > frame["high"])
        | (frame["open"] < frame["low"])
        | (frame["close"] > frame["high"])
        | (frame["close"] < frame["low"])
    ).any():
        raise MeanReversionRobustnessError("market frame contains invalid OHLC relationships")

    close = frame["close"]
    rolling_mean = close.rolling(lookback, min_periods=lookback).mean()
    rolling_std = close.rolling(lookback, min_periods=lookback).std(ddof=0)
    zscore = (close - rolling_mean) / rolling_std.replace(0.0, float("nan"))

    in_position = False
    values: list[float] = []
    for index in range(len(close)):
        z = zscore.iloc[index]
        if pd.notna(z):
            if in_position and z >= exit_z:
                in_position = False
            elif not in_position and z <= entry_z:
                in_position = True
        values.append(1.0 if in_position else 0.0)

    return pd.Series(
        values,
        index=market_frame.index,
        dtype="float64",
        name="target_exposure",
    )


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
            raise MeanReversionRobustnessError(f"metric became non-finite: {key}")
        cleaned[key] = int(value) if isinstance(value, int) else numeric
    return cleaned


def run_mean_reversion_robustness(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    if initial_cash <= 0:
        raise MeanReversionRobustnessError("initial_cash must be positive")

    runs: list[dict[str, object]] = []
    summaries: dict[str, object] = {}

    for profile_id, profile in EXECUTION_PROFILES.items():
        fee_bps = float(profile["fee_bps"])
        slippage_bps = float(profile["slippage_bps"])
        benchmark = _backtest(
            market_frame,
            pd.Series(1.0, index=market_frame.index, dtype="float64"),
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
        )
        benchmark_return = float(benchmark["metric_total_return"])

        profile_runs: list[dict[str, object]] = []
        for lookback, entry_z, exit_z in PARAMETER_GRID:
            metrics = _backtest(
                market_frame,
                build_mean_reversion_targets(market_frame, lookback, entry_z, exit_z),
                initial_cash=initial_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            total_return = float(metrics["metric_total_return"])
            entry = {
                "profile_id": profile_id,
                "lookback": lookback,
                "entry_z": entry_z,
                "exit_z": exit_z,
                "benchmark_total_return": benchmark_return,
                "excess_return_vs_buy_hold": total_return - benchmark_return,
                **metrics,
            }
            profile_runs.append(entry)
            runs.append(entry)

        returns = [float(item["metric_total_return"]) for item in profile_runs]
        excess = [float(item["excess_return_vs_buy_hold"]) for item in profile_runs]
        fills = [int(float(item.get("fill_count", 0))) for item in profile_runs]
        summaries[profile_id] = {
            "benchmark_total_return": benchmark_return,
            "median_total_return": median(returns),
            "worst_total_return": min(returns),
            "best_total_return": max(returns),
            "median_excess_return_vs_buy_hold": median(excess),
            "positive_return_fraction": sum(value > 0 for value in returns) / len(returns),
            "positive_excess_fraction": sum(value > 0 for value in excess) / len(excess),
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
        "hypothesis": "long-only rolling-zscore mean reversion on completed 4h bars",
        "parameter_grid": [
            {"lookback": lookback, "entry_z": entry_z, "exit_z": exit_z}
            for lookback, entry_z, exit_z in PARAMETER_GRID
        ],
        "execution_profiles": EXECUTION_PROFILES,
        "runs": runs,
        "profile_summaries": summaries,
        "kill_conditions": kill_conditions,
        "research_disposition": disposition,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
