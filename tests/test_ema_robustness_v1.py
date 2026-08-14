from __future__ import annotations

import math

import pandas as pd
import pytest

from ema_robustness_v1 import EmaRobustnessError, PARAMETER_GRID, build_ema_targets, run_ema_robustness
from scripts.run_ema_robustness_v1 import select_research_series


def make_market(rows: int = 180) -> pd.DataFrame:
    timestamps = pd.date_range("2025-01-01T00:00:00Z", periods=rows, freq="4h", tz="UTC")
    closes = [100.0 + 0.12 * index + 4.0 * math.sin(index / 8.0) for index in range(rows)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": closes,
            "high": [value + 0.8 for value in closes],
            "low": [value - 0.8 for value in closes],
            "close": closes,
        }
    )


def test_robustness_is_deterministic_and_bounded() -> None:
    market = make_market()
    first = run_ema_robustness(market)
    second = run_ema_robustness(market)

    assert first == second
    assert first["authority"] == "research-backtest-paper-only"
    assert first["automatic_promotion_allowed"] is False
    assert len(first["runs"]) == len(PARAMETER_GRID) * 2
    assert set(first["profile_summaries"]) == {"base", "stress"}
    assert set(first["kill_conditions"]) == {
        "all_stress_variants_inactive",
        "all_stress_variants_negative",
        "all_stress_variants_trail_buy_hold",
    }


def test_robustness_uses_next_bar_engine_and_finite_metrics() -> None:
    result = run_ema_robustness(make_market())
    for run in result["runs"]:
        assert run["fill_count"] >= 0
        assert math.isfinite(float(run["metric_total_return"]))
        assert math.isfinite(float(run["excess_return_vs_buy_hold"]))
        assert math.isfinite(float(run["sharpe"]))


def test_invalid_parameter_pair_fails_closed() -> None:
    with pytest.raises(EmaRobustnessError, match="fast < slow"):
        build_ema_targets(make_market(), 50, 20)


def test_series_selection_prefers_largest_ready_hour4_sets() -> None:
    status = pd.DataFrame(
        [
            {"symbol": "aero_usdt", "timeframe": "hour4", "rows": 3603, "integrity_ok": True, "status": "current"},
            {"symbol": "agt_usdt", "timeframe": "hour4", "rows": 2716, "integrity_ok": True, "status": "current"},
            {"symbol": "btc_usdt", "timeframe": "hour4", "rows": 10097, "integrity_ok": False, "status": "invalid"},
            {"symbol": "aero_usdt", "timeframe": "hour1", "rows": 14400, "integrity_ok": False, "status": "invalid"},
        ]
    )

    assert select_research_series(status) == [("aero_usdt", "hour4"), ("agt_usdt", "hour4")]
