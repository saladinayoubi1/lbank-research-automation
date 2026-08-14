from __future__ import annotations

import pandas as pd
import pytest

from mean_reversion_robustness_v1 import (
    MeanReversionRobustnessError,
    build_mean_reversion_targets,
    run_mean_reversion_robustness,
)


def _frame(closes: list[float]) -> pd.DataFrame:
    close = pd.Series(closes, dtype="float64")
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=len(close), freq="4h", tz="UTC"),
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1.0,
        }
    )


def test_signal_waits_for_full_lookback_and_enters_only_after_downside_extreme():
    closes = [100.0] * 19 + [90.0, 89.0, 100.0]
    targets = build_mean_reversion_targets(_frame(closes), 20, -1.5, -0.25)
    assert targets.iloc[:19].eq(0.0).all()
    assert targets.iloc[19] == 1.0
    assert targets.iloc[-1] == 0.0


def test_constant_prices_do_not_create_false_signal():
    targets = build_mean_reversion_targets(_frame([100.0] * 40), 20, -1.5, -0.25)
    assert targets.eq(0.0).all()


def test_invalid_ohlc_fails_closed():
    frame = _frame([100.0] * 30)
    frame.loc[4, "high"] = 50.0
    with pytest.raises(MeanReversionRobustnessError, match="invalid OHLC"):
        build_mean_reversion_targets(frame, 20, -1.5, -0.25)


def test_invalid_threshold_order_fails_closed():
    with pytest.raises(MeanReversionRobustnessError, match="strictly below"):
        build_mean_reversion_targets(_frame([100.0] * 30), 20, -0.5, -1.0)


def test_robustness_contract_has_cost_stress_benchmark_and_no_auto_promotion():
    closes = [100 + ((i % 24) - 12) * 0.45 + i * 0.015 for i in range(360)]
    result = run_mean_reversion_robustness(_frame(closes))
    assert result["execution_profiles"]["stress"] == {"fee_bps": 20.0, "slippage_bps": 10.0}
    assert len(result["runs"]) == 6
    assert "benchmark_total_return" in result["profile_summaries"]["stress"]
    assert set(result["kill_conditions"]) == {
        "all_stress_variants_inactive",
        "all_stress_variants_negative",
        "all_stress_variants_trail_buy_hold",
    }
    assert result["authority"] == "research-backtest-paper-only"
    assert result["automatic_promotion_allowed"] is False
