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

import bybit_consensus_search_v5 as base
import bybit_portfolio_search_v3 as market_utils


class RegimeSearchError(RuntimeError):
    pass


def candidate_id(params: dict[str, Any]) -> str:
    raw = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def enumerate_candidates(config: dict[str, Any]) -> list[dict[str, Any]]:
    search = config["search"]
    output: list[dict[str, Any]] = []
    for values in itertools.product(
        search["lookback_sets"],
        search["ema_fast_days"],
        search["deadband"],
        search["short_scale"],
        search["regime_fast_days"],
        search["regime_slow_days"],
        search["regime_threshold"],
        search["transition_scale"],
        search["vol_days"],
        search["target_vol"],
        search["rebalance_days"],
    ):
        (
            lookbacks,
            ema_fast,
            deadband,
            short_scale,
            regime_fast,
            regime_slow,
            regime_threshold,
            transition_scale,
            vol_days,
            target_vol,
            rebalance_days,
        ) = values
        params = {
            "lookbacks": lookbacks,
            "long_vote": search["long_vote"],
            "short_vote": search["short_vote"],
            "ema_fast_days": ema_fast,
            "ema_slow_days": search["ema_slow_days"],
            "deadband": deadband,
            "short_scale": short_scale,
            "fast_reversal": search["fast_reversal"],
            "regime_fast_days": regime_fast,
            "regime_slow_days": regime_slow,
            "regime_threshold": regime_threshold,
            "transition_scale": transition_scale,
            "vol_days": vol_days,
            "target_vol": target_vol,
            "rebalance_days": rebalance_days,
            "vol_ratio_trigger": search["vol_ratio_trigger"],
            "high_vol_scale": search["high_vol_scale"],
            "quantum": search["quantum"],
        }
        output.append({
            "id": candidate_id(params),
            "family": "explicit_regime_consensus",
            "params": params,
        })
    return output


def structural_key(candidate: dict[str, Any]) -> str:
    excluded = {
        "vol_days",
        "target_vol",
        "rebalance_days",
        "vol_ratio_trigger",
        "high_vol_scale",
        "quantum",
    }
    return json.dumps(
        {
            key: value
            for key, value in candidate["params"].items()
            if key not in excluded
        },
        sort_keys=True,
    )


def structural_signal(
    market: dict[str, Any], candidate: dict[str, Any]
) -> np.ndarray:
    close = market["close"]
    params = candidate["params"]
    returns = np.stack(
        [base.lag_return(close, int(days)) for days in params["lookbacks"]],
        axis=2,
    )
    positive_votes = np.mean(returns > 0.0, axis=2)
    negative_votes = np.mean(returns < 0.0, axis=2)
    median_return = np.nanmedian(returns, axis=2)
    fast_return = base.lag_return(close, 30)

    fast = np.column_stack([
        pd.Series(close[:, asset]).ewm(
            span=market_utils.bars(int(params["ema_fast_days"])),
            adjust=False,
            min_periods=market_utils.bars(int(params["ema_fast_days"])),
        ).mean().to_numpy(float)
        for asset in range(close.shape[1])
    ])
    slow = np.column_stack([
        pd.Series(close[:, asset]).ewm(
            span=market_utils.bars(int(params["ema_slow_days"])),
            adjust=False,
            min_periods=market_utils.bars(int(params["ema_slow_days"])),
        ).mean().to_numpy(float)
        for asset in range(close.shape[1])
    ])
    ema_score = fast / slow - 1.0

    asset_long = (
        (positive_votes >= float(params["long_vote"]))
        & (median_return > float(params["deadband"]))
        & (ema_score > 0.0)
        & (fast_return > -float(params["fast_reversal"]))
    )
    asset_short = (
        (negative_votes >= float(params["short_vote"]))
        & (median_return < -float(params["deadband"]))
        & (ema_score < 0.0)
        & (fast_return < float(params["fast_reversal"]))
    )

    broad_fast = np.nanmedian(
        base.lag_return(close, int(params["regime_fast_days"])),
        axis=1,
    )
    broad_slow = np.nanmedian(
        base.lag_return(close, int(params["regime_slow_days"])),
        axis=1,
    )
    threshold = float(params["regime_threshold"])
    bull = (broad_fast > threshold) & (broad_slow > 0.0)
    bear = (broad_fast < -threshold) & (broad_slow < 0.0)
    transition = ~(bull | bear)

    signal = np.zeros_like(close, dtype=float)
    long_scale = np.where(
        bull,
        1.0,
        np.where(transition, float(params["transition_scale"]), 0.0),
    )
    signal[asset_long] = np.broadcast_to(
        long_scale[:, None], close.shape
    )[asset_long]
    short_mask = asset_short & bear[:, None]
    signal[short_mask] = -float(params["short_scale"])
    signal[~np.isfinite(ema_score)] = 0.0
    return signal


def run_search(manifest_path: Path, output_root: Path) -> dict[str, Any]:
    base.enumerate_candidates = enumerate_candidates
    base.structural_key = structural_key
    base.structural_signal = structural_signal
    report = base.run_search(manifest_path, output_root)
    report["search_version"] = 6
    report["architecture"] = {
        "states": ["bull", "bear", "transition"],
        "bull": "long consensus allowed",
        "bear": "confirmed short consensus allowed",
        "transition": "long exposure scaled down; short disabled",
    }
    qualified = report["summary"][
        "qualifies_for_derivatives_validation_and_prospective_paper_forward"
    ]
    report["decision"] = (
        "eligible_for_derivatives_validation_and_prospective_paper_forward"
        if qualified
        else "continue_research_no_promotion"
    )
    (output_root / "regime_search_v6.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(
        output_root / "selected_consensus_strategy.json",
        output_root / "selected_regime_strategy.json",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("experiments/bybit_regime_search_v6.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("build/bybit_regime_search_v6"),
    )
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    report = run_search(args.manifest, args.output)
    print(json.dumps(report["summary"], sort_keys=True))
    qualified = report["summary"][
        "qualifies_for_derivatives_validation_and_prospective_paper_forward"
    ]
    return 1 if args.require_qualified and not qualified else 0


if __name__ == "__main__":
    raise SystemExit(main())
