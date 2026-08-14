from __future__ import annotations

from math import isfinite
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from performance_metrics import calculate_performance_metrics

PARAMETER_GRID = ((15, 40), (20, 50), (25, 60))
EXECUTION_PROFILES = {
    "base": {"fee_bps": 10.0, "slippage_bps": 5.0},
    "stress": {"fee_bps": 20.0, "slippage_bps": 10.0},
}


class EmaRobustnessError(RuntimeError):
    pass


def build_ema_targets(market_frame: pd.DataFrame, fast_span: int, slow_span: int) -> pd.Series:
    if not isinstance(fast_span, int) or not isinstance(slow_span, int):
        raise EmaRobustnessError("EMA spans must be integers")
    if fast_span < 2 or slow_span < 3 or fast_span >= slow_span:
        raise EmaRobustnessError("EMA spans must satisfy 2 <= fast < slow")
    if "close" not in market_frame:
        raise EmaRobustnessError("market frame is missing close")

    close = pd.to_numeric(market_frame["close"], errors="coerce")
    if close.isna().any() or (close <= 0).any():
        raise EmaRobustnessError("close must contain positive numeric values")

    fast = close.ewm(span=fast_span, adjust=False, min_periods=fast_span).mean()
    slow = close.ewm(span=slow_span, adjust=False, min_periods=slow_span).mean()
    eligible = fast.notna() & slow.notna()
    targets = ((fast > slow) & eligible).astype("float64")
    targets.name = "target_exposure"
    return targets


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
            raise EmaRobustnessError(f"metric became non-finite: {key}")
        cleaned[key] = int(value) if isinstance(value, int) else numeric
    return cleaned


def run_ema_robustness(
    market_frame: pd.DataFrame,
    *,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    if initial_cash <= 0:
        raise EmaRobustnessError("initial_cash must be positive")

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
        for fast_span, slow_span in PARAMETER_GRID:
            metrics = _backtest(
                market_frame,
                build_ema_targets(market_frame, fast_span, slow_span),
                initial_cash=initial_cash,
                fee_bps=fee_bps,
                slippage_bps=slippage_bps,
            )
            total_return = float(metrics["metric_total_return"])
            entry = {
                "profile_id": profile_id,
                "fast_span": fast_span,
                "slow_span": slow_span,
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

    return {
        "schema_version": 1,
        "parameter_grid": [
            {"fast_span": fast, "slow_span": slow} for fast, slow in PARAMETER_GRID
        ],
        "execution_profiles": EXECUTION_PROFILES,
        "runs": runs,
        "profile_summaries": summaries,
        "kill_conditions": kill_conditions,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
