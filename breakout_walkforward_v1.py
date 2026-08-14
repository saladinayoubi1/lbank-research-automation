from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from breakout_robustness_v1 import EXECUTION_PROFILES, PARAMETER_GRID, build_breakout_targets


class BreakoutWalkForwardError(RuntimeError):
    pass


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int = 720
    test_bars: int = 180
    step_bars: int = 180
    bootstrap_samples: int = 2000
    bootstrap_seed: int = 20260814

    def __post_init__(self) -> None:
        max_entry = max(entry for entry, _ in PARAMETER_GRID)
        if self.train_bars < max_entry + 2:
            raise BreakoutWalkForwardError("train_bars is too short for breakout warmup")
        if self.test_bars < 30:
            raise BreakoutWalkForwardError("test_bars must be at least 30")
        if self.step_bars < self.test_bars:
            raise BreakoutWalkForwardError(
                "step_bars must be at least test_bars so OOS folds do not overlap"
            )
        if self.bootstrap_samples < 200:
            raise BreakoutWalkForwardError("bootstrap_samples must be at least 200")


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise BreakoutWalkForwardError(f"market frame is missing columns: {missing}")
    if frame.empty:
        raise BreakoutWalkForwardError("market frame cannot be empty")
    normalized = frame.copy().reset_index(drop=True)
    normalized["timestamp"] = pd.to_datetime(
        normalized["timestamp"], utc=True, errors="raise"
    )
    if normalized["timestamp"].duplicated().any():
        raise BreakoutWalkForwardError("market timestamps must be unique")
    if not normalized["timestamp"].is_monotonic_increasing:
        raise BreakoutWalkForwardError("market timestamps must be sorted ascending")
    return normalized


def _run_window(
    frame: pd.DataFrame,
    targets: pd.Series,
    *,
    fee_bps: float,
    slippage_bps: float,
    initial_cash: float,
) -> dict[str, float | int]:
    result = run_target_exposure_backtest(
        frame,
        targets,
        BacktestConfig(
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            max_abs_exposure=1.0,
            liquidate_at_end=True,
        ),
    )
    metrics = result.metrics
    cleaned = {
        "total_return": float(metrics["total_return"]),
        "max_drawdown": float(metrics["max_drawdown"]),
        "fill_count": int(metrics["fill_count"]),
        "turnover_on_initial_cash": float(metrics["turnover_on_initial_cash"]),
    }
    if not all(isfinite(float(value)) for value in cleaned.values()):
        raise BreakoutWalkForwardError("walk-forward metric became non-finite")
    return cleaned


def _warm_test_targets(
    context: pd.DataFrame,
    *,
    test_start_offset: int,
    entry_window: int,
    exit_window: int,
) -> pd.Series:
    """Use pre-test bars only as indicator warmup and start each OOS fold flat."""
    if test_start_offset < 0 or test_start_offset >= len(context):
        raise BreakoutWalkForwardError("test_start_offset is outside the context")

    # Reuse the production rule validator, but deliberately do not reuse its
    # position state because OOS authority starts flat at the test boundary.
    build_breakout_targets(context, entry_window, exit_window)
    high = pd.to_numeric(context["high"], errors="raise")
    low = pd.to_numeric(context["low"], errors="raise")
    close = pd.to_numeric(context["close"], errors="raise")
    prior_high = high.shift(1).rolling(entry_window, min_periods=entry_window).max()
    prior_low = low.shift(1).rolling(exit_window, min_periods=exit_window).min()

    values = [0.0] * len(context)
    in_position = False
    for index in range(test_start_offset, len(context)):
        if in_position:
            if pd.notna(prior_low.iloc[index]) and close.iloc[index] < prior_low.iloc[index]:
                in_position = False
        elif pd.notna(prior_high.iloc[index]) and close.iloc[index] > prior_high.iloc[index]:
            in_position = True
        values[index] = 1.0 if in_position else 0.0

    return pd.Series(values, index=context.index, dtype="float64")


def _benchmark_targets(length: int, test_start_offset: int) -> pd.Series:
    """Enter Buy & Hold at the first OOS open under next-bar-open execution."""
    if length < 2 or test_start_offset <= 0 or test_start_offset >= length:
        raise BreakoutWalkForwardError("benchmark test boundary is outside the context")
    targets = pd.Series(0.0, index=range(length), dtype="float64")
    # The engine executes target[t] at open[t+1]. Emit the benchmark target on
    # the final warmup bar so its first fill is exactly the first OOS bar open.
    targets.iloc[test_start_offset - 1 :] = 1.0
    return targets


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise BreakoutWalkForwardError("cannot compute percentile of empty values")
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap_median_interval(
    values: list[float], *, samples: int, seed: int
) -> dict[str, float | int]:
    if len(values) < 3:
        raise BreakoutWalkForwardError(
            "at least three OOS folds are required for uncertainty"
        )
    rng = Random(seed)
    boot = []
    for _ in range(samples):
        draw = [values[rng.randrange(len(values))] for _ in values]
        boot.append(float(median(draw)))
    return {
        "samples": samples,
        "seed": seed,
        "median": float(median(values)),
        "lower_95": float(_percentile(boot, 0.025)),
        "upper_95": float(_percentile(boot, 0.975)),
    }


def run_breakout_walk_forward(
    market_frame: pd.DataFrame,
    *,
    config: WalkForwardConfig | None = None,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    cfg = config or WalkForwardConfig()
    if initial_cash <= 0 or not isfinite(float(initial_cash)):
        raise BreakoutWalkForwardError("initial_cash must be finite and positive")
    market = _validate_frame(market_frame)

    folds: list[dict[str, object]] = []
    start = 0
    fold_id = 0
    max_entry = max(entry for entry, _ in PARAMETER_GRID)

    while start + cfg.train_bars + cfg.test_bars <= len(market):
        train_start = start
        train_end = start + cfg.train_bars
        test_end = train_end + cfg.test_bars
        train = market.iloc[train_start:train_end].reset_index(drop=True)

        selection_profile = EXECUTION_PROFILES["stress"]
        train_scores = []
        for entry_window, exit_window in PARAMETER_GRID:
            metrics = _run_window(
                train,
                build_breakout_targets(train, entry_window, exit_window),
                fee_bps=float(selection_profile["fee_bps"]),
                slippage_bps=float(selection_profile["slippage_bps"]),
                initial_cash=initial_cash,
            )
            train_scores.append(
                {
                    "entry_window": entry_window,
                    "exit_window": exit_window,
                    "train_total_return": float(metrics["total_return"]),
                    "train_max_drawdown": float(metrics["max_drawdown"]),
                }
            )

        selected = max(
            train_scores,
            key=lambda item: (
                float(item["train_total_return"]),
                -float(item["train_max_drawdown"]),
                -int(item["entry_window"]),
                -int(item["exit_window"]),
            ),
        )
        entry_window = int(selected["entry_window"])
        exit_window = int(selected["exit_window"])

        warm_start = max(train_end - max_entry, 0)
        context = market.iloc[warm_start:test_end].reset_index(drop=True)
        test_start_offset = train_end - warm_start

        profile_results: dict[str, object] = {}
        for profile_id, profile in EXECUTION_PROFILES.items():
            strategy = _run_window(
                context,
                _warm_test_targets(
                    context,
                    test_start_offset=test_start_offset,
                    entry_window=entry_window,
                    exit_window=exit_window,
                ),
                fee_bps=float(profile["fee_bps"]),
                slippage_bps=float(profile["slippage_bps"]),
                initial_cash=initial_cash,
            )
            benchmark = _run_window(
                context,
                _benchmark_targets(len(context), test_start_offset),
                fee_bps=float(profile["fee_bps"]),
                slippage_bps=float(profile["slippage_bps"]),
                initial_cash=initial_cash,
            )
            profile_results[profile_id] = {
                "strategy_total_return": float(strategy["total_return"]),
                "benchmark_total_return": float(benchmark["total_return"]),
                "excess_return_vs_buy_hold": float(strategy["total_return"])
                - float(benchmark["total_return"]),
                "strategy_max_drawdown": float(strategy["max_drawdown"]),
                "strategy_fill_count": int(strategy["fill_count"]),
                "strategy_turnover_on_initial_cash": float(
                    strategy["turnover_on_initial_cash"]
                ),
            }

        folds.append(
            {
                "fold_id": fold_id,
                "train_start_utc": market.iloc[train_start]["timestamp"].isoformat(),
                "train_end_utc": market.iloc[train_end - 1]["timestamp"].isoformat(),
                "test_start_utc": market.iloc[train_end]["timestamp"].isoformat(),
                "test_end_utc": market.iloc[test_end - 1]["timestamp"].isoformat(),
                "selected_entry_window": entry_window,
                "selected_exit_window": exit_window,
                "selection_profile": "stress",
                "train_scores": train_scores,
                "oos": profile_results,
            }
        )
        fold_id += 1
        start += cfg.step_bars

    if len(folds) < 3:
        raise BreakoutWalkForwardError(
            f"insufficient data for three OOS folds: rows={len(market)}, folds={len(folds)}"
        )

    uncertainty: dict[str, object] = {}
    for profile_id in EXECUTION_PROFILES:
        excess = [
            float(fold["oos"][profile_id]["excess_return_vs_buy_hold"])
            for fold in folds
        ]
        returns = [
            float(fold["oos"][profile_id]["strategy_total_return"])
            for fold in folds
        ]
        uncertainty[profile_id] = {
            "fold_count": len(folds),
            "positive_strategy_fraction": sum(value > 0 for value in returns)
            / len(returns),
            "positive_excess_fraction": sum(value > 0 for value in excess) / len(excess),
            "median_excess_return_interval": _bootstrap_median_interval(
                excess,
                samples=cfg.bootstrap_samples,
                seed=cfg.bootstrap_seed + (0 if profile_id == "base" else 1),
            ),
        }

    stress_uncertainty = uncertainty["stress"]
    stress_interval = stress_uncertainty["median_excess_return_interval"]
    kill_conditions = {
        "stress_no_positive_oos_excess_folds": float(
            stress_uncertainty["positive_excess_fraction"]
        )
        == 0.0,
        "stress_median_excess_upper_bound_below_zero": float(stress_interval["upper_95"])
        < 0.0,
        "stress_majority_oos_returns_negative": float(
            stress_uncertainty["positive_strategy_fraction"]
        )
        < 0.5,
    }
    disposition = (
        "reject_hypothesis" if any(kill_conditions.values()) else "continue_research"
    )

    return {
        "schema_version": 1,
        "hypothesis": "long-only prior-range breakout with trailing range exit",
        "config": {
            "train_bars": cfg.train_bars,
            "test_bars": cfg.test_bars,
            "step_bars": cfg.step_bars,
            "bootstrap_samples": cfg.bootstrap_samples,
            "bootstrap_seed": cfg.bootstrap_seed,
        },
        "selection_rule": (
            "maximize stress-profile train total return; tie-break lower drawdown, "
            "then smaller entry and exit windows"
        ),
        "fold_start_state": "flat; pre-test bars are indicator warmup only",
        "folds": folds,
        "uncertainty": uncertainty,
        "kill_conditions": kill_conditions,
        "research_disposition": disposition,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
