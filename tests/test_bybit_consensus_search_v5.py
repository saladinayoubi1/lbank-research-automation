from __future__ import annotations

import numpy as np

from bybit_consensus_search_v5 import construct_weights, enumerate_candidates


def test_declared_candidate_count() -> None:
    config = {
        "search": {
            "lookback_sets": [[30, 90, 180]],
            "vote_pairs": [{"long": 0.5, "short": 0.67}],
            "ema_pairs": [{"fast": 20, "slow": 240}],
            "deadband": [0.0],
            "short_scale": [0.5],
            "fast_reversal": [0.03],
            "market_mode": ["asset"],
            "vol_days": [30, 90],
            "target_vol": [0.1, 0.2],
            "rebalance_days": [7],
            "vol_ratio_trigger": [1.5],
            "high_vol_scale": [0.25, 0.5],
            "quantum": 0.1,
        }
    }
    candidates = enumerate_candidates(config)
    assert len(candidates) == 8
    assert len({item["id"] for item in candidates}) == 8


def test_high_vol_circuit_reduces_weight() -> None:
    candidate = {
        "params": {
            "short_scale": 0.5,
            "target_vol": 0.2,
            "vol_ratio_trigger": 1.25,
            "high_vol_scale": 0.25,
            "rebalance_days": 1,
            "quantum": 0.1,
        }
    }
    signal = np.ones((12, 2), dtype=float)
    long_vol = np.full((12, 2), 0.2)
    fast_vol = np.full((12, 2), 0.2)
    fast_vol[6:] = 0.4
    weights = construct_weights(signal, long_vol, fast_vol, candidate)
    assert np.abs(weights[0]).sum() > np.abs(weights[-1]).sum()
    assert np.abs(weights[-1]).sum() <= 0.3
