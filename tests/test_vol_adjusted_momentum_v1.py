from __future__ import annotations

import pandas as pd
import pytest

from vol_adjusted_momentum_v1 import (
    VolAdjustedMomentumError,
    _buy_hold_total_return,
    build_vol_adjusted_momentum_targets,
    run_vol_adjusted_momentum_robustness,
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


def test_flat_series_does_not_create_false_momentum_signal():
    targets = build_vol_adjusted_momentum_targets(_frame([100.0] * 80), 24, 24, 1.0, 0.0)
    assert targets.eq(0.0).all()


def test_completed_bar_momentum_enters_only_after_score_is_available():
    closes = [100.0 + 0.05 * i for i in range(30)] + [103.0 + 1.5 * i for i in range(30)]
    targets = build_vol_adjusted_momentum_targets(_frame(closes), 24, 24, 0.5, 0.0)
    assert targets.iloc[:24].eq(0.0).all()
    assert targets.iloc[24:].max() == 1.0


def test_momentum_exit_occurs_after_score_reverses():
    closes = [100.0 + 1.0 * i for i in range(36)] + [136.0 - 1.5 * i for i in range(30)]
    targets = build_vol_adjusted_momentum_targets(_frame(closes), 12, 12, 0.75, 0.0)
    assert targets.max() == 1.0
    assert targets.iloc[-1] == 0.0


def test_duplicate_timestamp_fails_closed():
    frame = _frame([100.0 + i * 0.1 for i in range(40)])
    frame.loc[5, "timestamp"] = frame.loc[4, "timestamp"]
    with pytest.raises(VolAdjustedMomentumError, match="unique"):
        build_vol_adjusted_momentum_targets(frame, 24, 24, 1.0, 0.0)


def test_invalid_ohlc_fails_closed():
    frame = _frame([100.0 + i * 0.1 for i in range(40)])
    frame.loc[7, "high"] = 50.0
    with pytest.raises(VolAdjustedMomentumError, match="invalid OHLC"):
        build_vol_adjusted_momentum_targets(frame, 24, 24, 1.0, 0.0)


def test_invalid_threshold_order_fails_closed():
    with pytest.raises(VolAdjustedMomentumError, match="above exit_score"):
        build_vol_adjusted_momentum_targets(_frame([100.0] * 40), 24, 24, 0.0, 0.0)


def test_buy_hold_benchmark_starts_at_first_research_open():
    benchmark_return = _buy_hold_total_return(
        _frame([100.0, 110.0, 121.0]),
        initial_cash=10_000.0,
        fee_bps=0.0,
        slippage_bps=0.0,
    )
    assert benchmark_return == pytest.approx(0.21)


def test_robustness_contract_has_stress_benchmark_kill_gates_and_no_auto_promotion():
    closes = [100.0 + 0.04 * i + 1.5 * ((i % 24) / 24.0) for i in range(360)]
    result = run_vol_adjusted_momentum_robustness(_frame(closes))
    assert result["execution_profiles"]["stress"] == {"fee_bps": 20.0, "slippage_bps": 10.0}
    assert len(result["runs"]) == 6
    assert "benchmark_total_return" in result["profile_summaries"]["stress"]
    assert set(result["kill_conditions"]) == {
        "all_stress_variants_inactive",
        "all_stress_variants_negative",
        "all_stress_variants_trail_buy_hold",
    }
    assert result["research_disposition"] in {
        "reject_hypothesis",
        "continue_to_walkforward_validation",
    }
    assert result["authority"] == "research-backtest-paper-only"
    assert result["automatic_promotion_allowed"] is False
