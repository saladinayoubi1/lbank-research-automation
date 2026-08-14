from __future__ import annotations

from math import isfinite
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from performance_metrics import calculate_performance_metrics

PARAMETER_GRID = ((20, 10), (55, 20), (100, 40))
EXECUTION_PROFILES = {
    "base": {"fee_bps": 10.0, "slippage_bps": 5.0},
    "stress": {"fee_bps": 20.0, "slippage_bps": 10.0},
}


class BreakoutRobustnessError(RuntimeError):
    pass


def build_breakout_targets(
    market_frame: pd.DataFrame,
    entry_window: int,
    exit_window: int,
) -> pd.Series:
    """Build a long-only completed-bar breakout state without look-ahead."""
    if not isinstance(entry_window, int) or not isinstance(exit_window, int):
        raise BreakoutRobustnessError("breakout windows must be integers")
    if exit_window < 2 or entry_window < 3 or exit_window >= entry_window:
        raise BreakoutRobustnessError(
            "breakout windows must satisfy 2 <= exit_window < entry_window"
        )

    required = {"high", "low", "close"}
    missing = sorted(required - set(market_frame.columns))
    if missing:
        raise BreakoutRobustnessError(f"market frame is missing columns: {missing}")

    high = pd.to_numeric(market_frame["high"], errors="coerce")
    low = pd.to_numeric(market_frame["low"], errors="coerce")
    close = pd.to_numeric(market_frame["close"], errors="coerce")
    if high.isna().any() or low.isna().any() or close.isna().any():
        raise BreakoutRobustnessError("high/low/close must be numeric")
    if (high <= 0).any() or (low <= 0).any() or (close <= 0).any():
        raise BreakoutRobustnessError("high/low/close must be positive")
    if ((high < low) | (close > high) | (close < low)).any():
        raise BreakoutRobustnessError("market frame contains invalid OHLC relationships")

    prior_high = high.shift(1).rolling(
        entry_window, min_periods=entry_window
    ).max()
    prior_low = low.shift(1).rolling(
        exit_window, min_periods=exit_window
    ).min()

    in_position = False
    values: list[float] = []
    for index in range(len(market_frame)):
        if in_position:
            if pd.notna(prior_low.iloc[index]) and close.iloc[index] < prior_low.iloc[index]:
                in_position = False
        elif pd.notna(prior_high.iloc[index]) and close.iloc[index] > prior_high.iloc[index]:
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
            raise BreakoutRobustnessError(f"metric became non-finite: {key}")
        cleaned[key] = int(value) if isinstance(value, int) else numeric
    return cleaned


def run_breakout_robustness(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    if initial_cash <= 0:
        raise BreakoutRobustnessError("initial_cash must be positive")

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
        for entry_window, exit_window in PARAMETER_GRID:
            metrics = _backtest(
                market_frame,
                build_breakout_targets(market_frame, entry_window, exit_window),
                initial_cash=initial_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            total_return = float(metrics["metric_total_return"])
            entry = {
                "profile_id": profile_id,
                "entry_window": entry_window,
                "exit_window": exit_window,
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
        "hypothesis": "long-only prior-range breakout with trailing range exit",
        "parameter_grid": [
            {"entry_window": entry, "exit_window": exit_}
            for entry, exit_ in PARAMETER_GRID
        ],
        "execution_profiles": EXECUTION_PROFILES,
        "runs": runs,
        "profile_summaries": summaries,
        "kill_conditions": kill_conditions,
        "research_disposition": disposition,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
