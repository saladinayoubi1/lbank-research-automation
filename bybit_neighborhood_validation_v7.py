from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import bybit_consensus_search_v5 as evaluation
import bybit_long_short_search_v4 as engine
import bybit_portfolio_search_v3 as market_utils
import bybit_regime_search_v6 as regime


def candidate_id(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def candidate(params: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": candidate_id(params),
        "family": "frozen_regime_neighborhood",
        "params": params,
    }


def update(center: dict[str, Any], **changes: Any) -> dict[str, Any]:
    result = dict(center)
    result.update(changes)
    return result


def enumerate_neighborhood(config: dict[str, Any]) -> list[dict[str, Any]]:
    center = dict(config["frozen_components"][0])
    neighborhood = config["neighborhood"]
    values: dict[str, dict[str, Any]] = {}

    def add(params: dict[str, Any]) -> None:
        item = candidate(params)
        values[item["id"]] = item

    for params in config["frozen_components"]:
        add(dict(params))

    for lookbacks, ema_pair, deadband in itertools.product(
        neighborhood["lookback_sets"],
        neighborhood["ema_pairs"],
        neighborhood["deadband"],
    ):
        add(update(
            center,
            lookbacks=lookbacks,
            ema_fast_days=ema_pair[0],
            ema_slow_days=ema_pair[1],
            deadband=deadband,
        ))

    for fast, slow, threshold, transition in itertools.product(
        neighborhood["regime_fast_days"],
        neighborhood["regime_slow_days"],
        neighborhood["regime_threshold"],
        neighborhood["transition_scale"],
    ):
        add(update(
            center,
            regime_fast_days=fast,
            regime_slow_days=slow,
            regime_threshold=threshold,
            transition_scale=transition,
        ))

    for vol_days, target_vol, rebalance_days in itertools.product(
        neighborhood["vol_days"],
        neighborhood["target_vol"],
        neighborhood["rebalance_days"],
    ):
        add(update(
            center,
            vol_days=vol_days,
            target_vol=target_vol,
            rebalance_days=rebalance_days,
        ))

    for short_scale, threshold, target_vol in itertools.product(
        neighborhood["short_scale"],
        neighborhood["regime_threshold"],
        neighborhood["target_vol"],
    ):
        add(update(
            center,
            short_scale=short_scale,
            regime_threshold=threshold,
            target_vol=target_vol,
        ))

    return sorted(values.values(), key=lambda item: item["id"])


def build_weights(
    market: dict[str, Any],
    item: dict[str, Any],
    signal_cache: dict[str, np.ndarray],
    vol_cache: dict[int, np.ndarray],
    fast_vol: np.ndarray,
) -> np.ndarray:
    key = regime.structural_key(item)
    if key not in signal_cache:
        signal_cache[key] = regime.structural_signal(market, item)
    vol_days = int(item["params"]["vol_days"])
    if vol_days not in vol_cache:
        vol_cache[vol_days] = market_utils.realized_vol(
            market["close"], vol_days
        )
    return evaluation.construct_weights(
        signal_cache[key],
        vol_cache[vol_days],
        fast_vol,
        item,
    )


def evaluate_candidate(
    market: dict[str, Any],
    weights: np.ndarray,
    config: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    exact_runs: list[dict[str, Any]] = []
    summaries: dict[str, Any] = {}
    all_checks: dict[str, Any] = {}
    for profile_name in ["conservative", "stress"]:
        summary, rows = evaluation.evaluate(
            market,
            weights,
            config["folds"],
            config["execution"][profile_name],
            exact=True,
        )
        checks = engine.gate_checks(
            summary,
            config["gates"][profile_name],
        )
        summaries[profile_name] = summary
        all_checks[profile_name] = checks
        exact_runs.extend({
            "profile": profile_name,
            **row,
        } for row in rows)
    return {
        "conservative": summaries["conservative"],
        "stress": summaries["stress"],
        "conservative_checks": all_checks["conservative"],
        "stress_checks": all_checks["stress"],
        "passes": all(all_checks["conservative"].values())
        and all(all_checks["stress"].values()),
        "combined_score": summaries["conservative"]["score"]
        + 0.5 * summaries["stress"]["score"],
    }, exact_runs


def flatten(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "params": json.dumps(item["params"], sort_keys=True),
        "passes": item["passes"],
        "combined_score": item["combined_score"],
        **{
            f"conservative_{key}": value
            for key, value in item["conservative"].items()
        },
        **{
            f"stress_{key}": value
            for key, value in item["stress"].items()
        },
        "failed_conservative": json.dumps([
            name
            for name, passed in item["conservative_checks"].items()
            if not passed
        ]),
        "failed_stress": json.dumps([
            name
            for name, passed in item["stress_checks"].items()
            if not passed
        ]),
    }


def run_validation(
    manifest_path: Path, output_root: Path
) -> dict[str, Any]:
    config = json.loads(manifest_path.read_text(encoding="utf-8"))
    market = market_utils.load_market(
        Path(config["dataset"]["dataset_root"]),
        config["symbols"],
    )
    candidates = enumerate_neighborhood(config)
    signal_cache: dict[str, np.ndarray] = {}
    vol_cache: dict[int, np.ndarray] = {}
    fast_vol = market_utils.realized_vol(market["close"], 14)
    results: list[dict[str, Any]] = []
    all_runs: list[dict[str, Any]] = []
    weight_cache: dict[str, np.ndarray] = {}

    for item in candidates:
        weights = build_weights(
            market,
            item,
            signal_cache,
            vol_cache,
            fast_vol,
        )
        weight_cache[item["id"]] = weights
        metrics, runs = evaluate_candidate(market, weights, config)
        result = {**item, **metrics}
        results.append(result)
        all_runs.extend({
            "candidate_id": item["id"],
            **row,
        } for row in runs)

    results.sort(key=lambda item: item["combined_score"], reverse=True)
    passers = [item for item in results if item["passes"]]
    plateau = evaluation.parameter_plateau(passers, config)

    frozen_items = [candidate(dict(params)) for params in config["frozen_components"]]
    frozen_weights = np.median(
        np.stack([
            build_weights(
                market,
                item,
                signal_cache,
                vol_cache,
                fast_vol,
            )
            for item in frozen_items
        ], axis=2),
        axis=2,
    )
    gross = np.abs(frozen_weights).sum(axis=1)
    excessive = gross > 1.0
    frozen_weights[excessive] /= gross[excessive, None]
    frozen_metrics, frozen_runs = evaluate_candidate(
        market,
        frozen_weights,
        config,
    )
    frozen_passes = bool(frozen_metrics["passes"])
    qualifies = bool(frozen_passes and plateau["passes"])

    report = {
        "experiment_id": config["experiment_id"],
        "dataset_archive_sha256": config["dataset"]["archive_sha256"],
        "validation_type": "frozen_strategy_local_parameter_neighborhood",
        "selection_policy": (
            "The frozen four-component v6 ensemble is not reselected from "
            "neighborhood results. Neighborhoods are used only to establish "
            "or reject a parameter plateau."
        ),
        "summary": {
            "neighborhood_candidates": len(candidates),
            "dual_profile_passers": len(passers),
            "parameter_plateau": plateau,
            "frozen_strategy_passes": frozen_passes,
            "qualifies_for_derivatives_validation_and_prospective_paper_forward": qualifies,
            "automatic_paper_forward_started": False,
            "live_trading_enabled": False,
        },
        "frozen_strategy": {
            "type": "median_ensemble",
            "components": config["frozen_components"],
            **frozen_metrics,
        },
        "frozen_fold_runs": frozen_runs,
        "decision": (
            "eligible_for_derivatives_validation_and_prospective_paper_forward"
            if qualifies
            else "continue_research_no_promotion"
        ),
        "limitations": [
            "All available history has informed development; this is historical cross-validation and local sensitivity evidence, not a pristine out-of-sample test.",
            "Short exposure still requires separate perpetual-funding, margin, liquidation and execution validation.",
            "Parameters must remain frozen during the prospective paper-forward phase."
        ],
    }

    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "neighborhood_validation_v7.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "frozen_strategy.json").write_text(
        json.dumps(report["frozen_strategy"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame([flatten(item) for item in results]).to_csv(
        output_root / "neighborhood_candidates.csv", index=False
    )
    pd.DataFrame(all_runs).to_csv(
        output_root / "neighborhood_fold_runs.csv", index=False
    )
    pd.DataFrame(frozen_runs).to_csv(
        output_root / "frozen_fold_runs.csv", index=False
    )
    shutil.copy2(manifest_path, output_root / manifest_path.name)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/bybit_neighborhood_validation_v7.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/bybit_neighborhood_validation_v7"),
    )
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    report = run_validation(args.manifest, args.output)
    print(json.dumps(report["summary"], sort_keys=True))
    qualified = report["summary"][
        "qualifies_for_derivatives_validation_and_prospective_paper_forward"
    ]
    return 1 if args.require_qualified and not qualified else 0


if __name__ == "__main__":
    raise SystemExit(main())
