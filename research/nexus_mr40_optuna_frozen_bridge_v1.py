"""Optuna-only, research-only bridge for the frozen four-case MR40 replay.

An injected pure candle evaluator supplies results. All optimization trials use
historical TRAIN+STRESS only; evaluation occurs only after selecting the case.
Prior 2023–2026 observations are already seen, NOT genuinely prospective OOS.
No broker interfaces, no Paper state changes, no live trading permission.
"""
from __future__ import annotations

from collections.abc import Callable
from math import isfinite
from typing import Any

FROZEN_CASES = ("baseline", "vol40_only", "stop4_arm2_only", "vol40_stop4_arm2")
FROZEN_SEED = 19


class AdapterError(ValueError):
    pass


def _checked(metrics: Any, name: str) -> dict[str, Any]:
    if not isinstance(metrics, dict):
        raise AdapterError(f"invalid_metrics_type:{name}")
    for key in ("net_pnl_usdt", "max_intrabar_low_bound_pct", "closed_positions"):
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value):
            raise AdapterError(f"nonfinite_or_missing:{name}:{key}")
    if metrics["max_intrabar_low_bound_pct"] < 0 or metrics["closed_positions"] < 0:
        raise AdapterError(f"negative_risk_or_positions:{name}")
    if not float(metrics["closed_positions"]).is_integer():
        raise AdapterError(f"fractional_trades:{name}")
    return metrics


def frozen_optuna_replay(
    evaluate: Callable[[str, str, str], dict[str, Any]],
    *,
    cases: tuple[str, ...] = FROZEN_CASES,
    seed: int = FROZEN_SEED,
) -> dict[str, Any]:
    """Run exactly four Optuna trials, with post-selection evaluation only.

    evaluate(case, window, cost_profile) MUST be a pure, deterministic,
    source-locked, historical candle simulation. New candidate parameter
    sets are prohibited without a newly preregistered experiment.
    """
    if tuple(cases) != FROZEN_CASES:
        raise AdapterError("unregistered_cases")
    if seed != FROZEN_SEED:
        raise AdapterError("seed_drift")
    try:
        import optuna
    except ImportError as exc:
        raise AdapterError("optuna_not_installed_no_fallback") from exc

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    study = optuna.create_study(
        direction="maximize",
        sampler=optuna.samplers.GridSampler({"case": list(cases)}, seed=seed),
    )
    inspected: dict[str, dict[str, Any]] = {}

    def objective(trial: Any) -> float:
        case = trial.suggest_categorical("case", list(cases))
        if case in inspected:
            raise AdapterError("duplicate_train_trial")
        metrics = _checked(evaluate(case, "train", "stress"), "train:" + case)
        inspected[case] = dict(metrics)
        score = float(metrics["net_pnl_usdt"]) / max(float(metrics["max_intrabar_low_bound_pct"]), 1.0)
        if not isfinite(score):
            raise AdapterError("nonfinite_train_score")
        return score

    study.optimize(objective, n_trials=len(cases), n_jobs=1, show_progress_bar=False)
    if len(study.trials) != len(cases) or set(inspected) != set(cases):
        raise AdapterError("training_grid_incomplete")
    scores = {
        c: float(inspected[c]["net_pnl_usdt"]) / max(float(inspected[c]["max_intrabar_low_bound_pct"]), 1.0)
        for c in cases
    }
    chosen = max(cases, key=lambda c: (scores[c], -cases.index(c)))
    baseline = dict(_checked(evaluate("baseline", "evaluation", "stress"), "evaluation:baseline"))
    selected = baseline if chosen == "baseline" else dict(_checked(
        evaluate(chosen, "evaluation", "stress"), "evaluation:" + chosen
    ))
    return {
        "schema": "nexus.mr40.optuna_frozen_candle_adapter.v1",
        "mode": "research_only",
        "optimizer": "optuna.GridSampler",
        "optuna_version": optuna.__version__,
        "seed": seed,
        "cases": list(cases),
        "training_trials": len(study.trials),
        "training_window": "train",
        "training_cost_profile": "stress",
        "training_objective": "after_cost_pnl_usdt / max(intrabar_low_dd_percent, 1)",
        "train_scores": scores,
        "train_selected_case": chosen,
        "validation_access_after_all_training": True,
        "evaluation_baseline": baseline,
        "evaluation_selected": selected,
        "eval_profit_noninferior": selected["net_pnl_usdt"] >= baseline["net_pnl_usdt"],
        "historically_seen": True,
        "genuine_prospective_oos": False,
        "paper_promotion_authorized": False,
        "live": False,
        "real_orders": 0,
        "private_api": False,
    }
