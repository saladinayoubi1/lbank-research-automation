from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from random import Random
from statistics import median

import pandas as pd

from backtest_engine import BacktestConfig, run_target_exposure_backtest
from ema_robustness_v1 import EXECUTION_PROFILES, PARAMETER_GRID, build_ema_targets


class EmaWalkForwardError(RuntimeError):
    pass


@dataclass(frozen=True)
class WalkForwardConfig:
    train_bars: int = 360
    test_bars: int = 120
    step_bars: int = 120
    bootstrap_samples: int = 2000
    bootstrap_seed: int = 20260814

    def __post_init__(self) -> None:
        if self.train_bars < max(slow for _, slow in PARAMETER_GRID) + 2:
            raise EmaWalkForwardError("train_bars is too short for EMA warmup")
        if self.test_bars < 20:
            raise EmaWalkForwardError("test_bars must be at least 20")
        if self.step_bars < 1:
            raise EmaWalkForwardError("step_bars must be positive")
        if self.step_bars < self.test_bars:
            raise EmaWalkForwardError(
                "step_bars must be at least test_bars so OOS folds do not overlap"
            )
        if self.bootstrap_samples < 200:
            raise EmaWalkForwardError("bootstrap_samples must be at least 200")


def _validate_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"timestamp", "open", "high", "low", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise EmaWalkForwardError(f"market frame is missing columns: {missing}")
    if frame.empty:
        raise EmaWalkForwardError("market frame cannot be empty")
    normalized = frame.copy().reset_index(drop=True)
    normalized["timestamp"] = pd.to_datetime(normalized["timestamp"], utc=True, errors="raise")
    if normalized["timestamp"].duplicated().any():
        raise EmaWalkForwardError("market timestamps must be unique")
    if not normalized["timestamp"].is_monotonic_increasing:
        raise EmaWalkForwardError("market timestamps must be sorted ascending")
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
        raise EmaWalkForwardError("walk-forward metric became non-finite")
    return cleaned


def _warm_test_targets(
    context: pd.DataFrame,
    *,
    test_start_offset: int,
    fast_span: int,
    slow_span: int,
) -> pd.Series:
    raw = build_ema_targets(context, fast_span, slow_span).reset_index(drop=True)
    raw.iloc[:test_start_offset] = 0.0
    return raw


def _benchmark_targets(length: int, test_start_offset: int) -> pd.Series:
    targets = pd.Series(0.0, index=range(length), dtype="float64")
    targets.iloc[test_start_offset:] = 1.0
    return targets


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise EmaWalkForwardError("cannot compute percentile of empty values")
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _bootstrap_median_interval(
    values: list[float], *, samples: int, seed: int
) -> dict[str, float | int]:
    if len(values) < 3:
        raise EmaWalkForwardError("at least three OOS folds are required for uncertainty")
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


def run_ema_walk_forward(
    market_frame: pd.DataFrame,
    *,
    config: WalkForwardConfig | None = None,
    initial_cash: float = 10_000.0,
) -> dict[str, object]:
    cfg = config or WalkForwardConfig()
    if initial_cash <= 0 or not isfinite(float(initial_cash)):
        raise EmaWalkForwardError("initial_cash must be finite and positive")
    market = _validate_frame(market_frame)

    folds: list[dict[str, object]] = []
    start = 0
    fold_id = 0
    max_slow = max(slow for _, slow in PARAMETER_GRID)

    while start + cfg.train_bars + cfg.test_bars <= len(market):
        train_start = start
        train_end = start + cfg.train_bars
        test_end = train_end + cfg.test_bars
        train = market.iloc[train_start:train_end].reset_index(drop=True)

        selection_profile = EXECUTION_PROFILES["stress"]
        train_scores = []
        for fast_span, slow_span in PARAMETER_GRID:
            metrics = _run_window(
                train,
                build_ema_targets(train, fast_span, slow_span),
                fee_bps=float(selection_profile["fee_bps"]),
                slippage_bps=float(selection_profile["slippage_bps"]),
                initial_cash=initial_cash,
            )
            train_scores.append(
                {
                    "fast_span": fast_span,
                    "slow_span": slow_span,
                    "train_total_return": float(metrics["total_return"]),
                    "train_max_drawdown": float(metrics["max_drawdown"]),
                }
            )

        selected = max(
            train_scores,
            key=lambda item: (
                float(item["train_total_return"]),
                -float(item["train_max_drawdown"]),
                -int(item["slow_span"]),
                -int(item["fast_span"]),
            ),
        )
        fast_span = int(selected["fast_span"])
        slow_span = int(selected["slow_span"])

        warm_start = max(train_end - max_slow, 0)
        context = market.iloc[warm_start:test_end].reset_index(drop=True)
        test_start_offset = train_end - warm_start

        profile_results: dict[str, object] = {}
        for profile_id, profile in EXECUTION_PROFILES.items():
            strategy = _run_window(
                context,
                _warm_test_targets(
                    context,
                    test_start_offset=test_start_offset,
                    fast_span=fast_span,
                    slow_span=slow_span,
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
                "selected_fast_span": fast_span,
                "selected_slow_span": slow_span,
                "selection_profile": "stress",
                "train_scores": train_scores,
                "oos": profile_results,
            }
        )
        fold_id += 1
        start += cfg.step_bars

    if len(folds) < 3:
        raise EmaWalkForwardError(
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
            "positive_strategy_fraction": sum(value > 0 for value in returns) / len(returns),
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
        ) == 0.0,
        "stress_median_excess_upper_bound_below_zero": float(stress_interval["upper_95"])
        < 0.0,
        "stress_majority_oos_returns_negative": float(
            stress_uncertainty["positive_strategy_fraction"]
        ) < 0.5,
    }

    return {
        "schema_version": 1,
        "config": {
            "train_bars": cfg.train_bars,
            "test_bars": cfg.test_bars,
            "step_bars": cfg.step_bars,
            "bootstrap_samples": cfg.bootstrap_samples,
            "bootstrap_seed": cfg.bootstrap_seed,
        },
        "selection_rule": "maximize stress-profile train total return; tie-break lower drawdown then smaller spans",
        "folds": folds,
        "uncertainty": uncertainty,
        "kill_conditions": kill_conditions,
        "authority": "research-backtest-paper-only",
        "automatic_promotion_allowed": False,
    }
