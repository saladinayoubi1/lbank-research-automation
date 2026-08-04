from __future__ import annotations

import pandas as pd
import pytest

from bybit_benchmark_v1 import (
    BybitBenchmarkError,
    build_target_exposures,
    evaluate_qualification,
    validate_status_row,
)


def market_frame(closes: list[float]) -> pd.DataFrame:
    timestamp = pd.date_range("2025-01-01", periods=len(closes), freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamp,
            "open": closes,
            "high": [value + 1 for value in closes],
            "low": [value - 1 for value in closes],
            "close": closes,
            "volume": 1.0,
            "symbol": "btc_usdt",
            "timeframe": "hour4",
        }
    )


def test_buy_and_hold_targets_full_exposure() -> None:
    frame = market_frame([100, 101, 102])
    targets = build_target_exposures(frame, {"strategy_id": "buy_and_hold"})
    assert targets.tolist() == [1.0, 1.0, 1.0]


def test_sma_target_requires_valid_windows() -> None:
    frame = market_frame([100, 101, 102, 103])
    with pytest.raises(BybitBenchmarkError):
        build_target_exposures(
            frame,
            {
                "strategy_id": "sma_long_flat",
                "parameters": {"fast_window": 5, "slow_window": 5},
            },
        )


def test_donchian_uses_prior_window_and_can_exit() -> None:
    frame = market_frame([10, 11, 12, 13, 14, 15, 9, 8])
    targets = build_target_exposures(
        frame,
        {
            "strategy_id": "donchian_long_flat",
            "parameters": {"entry_window": 3, "exit_window": 2},
        },
    )
    assert targets.iloc[:3].tolist() == [0.0, 0.0, 0.0]
    assert 1.0 in targets.tolist()
    assert targets.iloc[-1] == 0.0


def test_status_gate_requires_ready_and_zero_integrity_counts() -> None:
    status = pd.DataFrame(
        [
            {
                "symbol": "btc_usdt",
                "timeframe": "hour4",
                "rows": 8034,
                "expected_rows": 8034,
                "integrity_ok": True,
                "status": "ready",
                "missing_candles": 0,
                "gap_count": 0,
                "duplicate_count": 0,
                "off_grid_count": 0,
                "invalid_ohlc_count": 0,
            }
        ]
    )
    row = validate_status_row(status, "btc_usdt", "hour4", 8000)
    assert row["status"] == "ready"
    status.loc[0, "gap_count"] = 1
    with pytest.raises(BybitBenchmarkError):
        validate_status_row(status, "btc_usdt", "hour4", 8000)


def test_qualification_requires_both_symbols_to_pass() -> None:
    manifest = {
        "series": [
            {"symbol": "btc_usdt", "timeframe": "hour4"},
            {"symbol": "eth_usdt", "timeframe": "hour4"},
        ],
        "strategies": [
            {"strategy_id": "buy_and_hold"},
            {"strategy_id": "sma_long_flat"},
        ],
        "qualification_policy": {
            "period": "holdout",
            "profile_id": "conservative",
            "benchmark_strategy_id": "buy_and_hold",
            "minimum_total_return": 0.0,
            "minimum_median_total_return": 0.0,
            "maximum_drawdown": 0.25,
            "minimum_sharpe_like": 0.0,
            "minimum_fill_count": 4,
        },
    }
    runs = [
        {
            "symbol": symbol,
            "timeframe": "hour4",
            "strategy_id": "sma_long_flat",
            "profile_id": "conservative",
            "period": "holdout",
            "success": True,
            "total_return": 0.10,
            "max_drawdown": 0.10,
            "sharpe_like_zero_rate": 0.5,
            "fill_count": 10,
        }
        for symbol in ["btc_usdt", "eth_usdt"]
    ]
    result = evaluate_qualification(runs, manifest)
    assert len(result) == 1
    assert result[0]["qualifies_for_paper_forward_review"] is True

    runs[1]["total_return"] = -0.01
    result = evaluate_qualification(runs, manifest)
    assert result[0]["qualifies_for_paper_forward_review"] is False
    assert "all_returns_positive" in result[0]["failed_checks"]
