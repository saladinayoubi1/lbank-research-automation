from __future__ import annotations

import json
from pathlib import Path

from mean_reversion_robustness_v1 import run_mean_reversion_robustness
from research_data import load_research_series

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "market"


def test_frozen_fresh_snapshot_executes_mean_reversion_robustness_without_promotion(capsys):
    summaries = {}
    for symbol in ("aero_usdt", "agt_usdt"):
        frame = load_research_series(symbol, "hour4", data_root=DATA_ROOT, minimum_rows=500)
        result = run_mean_reversion_robustness(frame)
        stress = result["profile_summaries"]["stress"]
        summaries[symbol] = {
            "rows": len(frame),
            "last_candle_utc": frame.iloc[-1]["timestamp"].isoformat(),
            "stress_benchmark_total_return": stress["benchmark_total_return"],
            "stress_median_total_return": stress["median_total_return"],
            "stress_best_total_return": stress["best_total_return"],
            "stress_median_excess_return_vs_buy_hold": stress["median_excess_return_vs_buy_hold"],
            "stress_positive_return_fraction": stress["positive_return_fraction"],
            "stress_positive_excess_fraction": stress["positive_excess_fraction"],
            "kill_conditions": result["kill_conditions"],
            "research_disposition": result["research_disposition"],
        }
        assert result["authority"] == "research-backtest-paper-only"
        assert result["automatic_promotion_allowed"] is False
        assert result["research_disposition"] in {"reject_hypothesis", "continue_to_walkforward_validation"}
    with capsys.disabled():
        print("MEAN_REVERSION_EMPIRICAL=" + json.dumps(summaries, sort_keys=True), flush=True)
