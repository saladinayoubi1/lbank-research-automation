from __future__ import annotations

from bybit_neighborhood_validation_v7 import enumerate_neighborhood


def test_neighborhood_is_deduplicated_and_contains_frozen_components() -> None:
    center = {
        "lookbacks": [30, 90, 180],
        "ema_fast_days": 45,
        "ema_slow_days": 240,
        "deadband": 0.03,
        "short_scale": 0.25,
        "regime_fast_days": 30,
        "regime_slow_days": 120,
        "regime_threshold": 0.03,
        "transition_scale": 0.25,
        "vol_days": 90,
        "target_vol": 0.10,
        "rebalance_days": 7,
        "fast_reversal": 0.03,
        "high_vol_scale": 0.50,
        "long_vote": 0.50,
        "quantum": 0.10,
        "short_vote": 0.67,
        "vol_ratio_trigger": 1.25,
    }
    config = {
        "frozen_components": [center, dict(center, short_scale=0.50)],
        "neighborhood": {
            "lookback_sets": [[30, 90, 180]],
            "ema_pairs": [[45, 240]],
            "deadband": [0.03],
            "regime_fast_days": [30],
            "regime_slow_days": [120],
            "regime_threshold": [0.03],
            "transition_scale": [0.25],
            "vol_days": [90],
            "target_vol": [0.10],
            "rebalance_days": [7],
            "short_scale": [0.25, 0.50],
        },
    }
    candidates = enumerate_neighborhood(config)
    assert len(candidates) == 2
    assert len({item["id"] for item in candidates}) == 2
