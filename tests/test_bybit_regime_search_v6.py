from __future__ import annotations

import numpy as np
import pandas as pd

from bybit_regime_search_v6 import enumerate_candidates, structural_signal


def test_declared_regime_candidate_count() -> None:
    config = {
        "search": {
            "lookback_sets": [[30, 90, 180]],
            "ema_fast_days": [20],
            "deadband": [0.0],
            "short_scale": [0.25],
            "regime_fast_days": [30, 60],
            "regime_slow_days": [120],
            "regime_threshold": [0.0],
            "transition_scale": [0.0, 0.25],
            "vol_days": [30],
            "target_vol": [0.1],
            "rebalance_days": [7],
            "quantum": 0.1,
            "ema_slow_days": 240,
            "long_vote": 0.5,
            "short_vote": 0.67,
            "fast_reversal": 0.03,
            "vol_ratio_trigger": 1.25,
            "high_vol_scale": 0.5,
        }
    }
    assert len(enumerate_candidates(config)) == 4


def test_transition_state_scales_long_signal() -> None:
    timestamps = pd.date_range("2023-01-01", periods=2500, freq="4h", tz="UTC")
    first = np.linspace(100.0, 180.0, 1800)
    second = np.linspace(180.0, 165.0, 700)
    btc = np.r_[first, second]
    eth = np.r_[first * 0.9, second * 0.9]
    close = np.column_stack([btc, eth])
    market = {
        "timestamps": pd.Series(timestamps),
        "open": close.copy(),
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "symbols": ["btc_usdt", "eth_usdt"],
    }
    base_params = {
        "lookbacks": [30, 90, 180],
        "long_vote": 0.5,
        "short_vote": 0.67,
        "ema_fast_days": 20,
        "ema_slow_days": 240,
        "deadband": 0.0,
        "short_scale": 0.25,
        "fast_reversal": 0.03,
        "regime_fast_days": 30,
        "regime_slow_days": 240,
        "regime_threshold": 0.0,
        "transition_scale": 0.0,
    }
    zero_transition = structural_signal(
        market, {"params": base_params}
    )
    scaled_params = dict(base_params, transition_scale=0.25)
    scaled_transition = structural_signal(
        market, {"params": scaled_params}
    )
    assert np.abs(scaled_transition).sum() >= np.abs(zero_transition).sum()
