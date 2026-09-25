from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

import nexus_low_turnover_hypothesis_v1 as low
import nexus_multitimeframe_strategy_discovery as discovery

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_low_turnover_hypothesis_v1.json"


def _closed_frame(count: int = 210) -> pd.DataFrame:
    times = pd.date_range("2024-01-01T00:00:00Z", periods=count, freq="4h", tz="UTC")
    closes = [100 + 9 * math.sin(index / 4) + index * 0.03 for index in range(count)]
    return pd.DataFrame({"timestamp": times, "close": closes, "open": closes})


def test_manifest_is_exactly_two_unpromotable_cost_aware_variants(tmp_path: Path) -> None:
    assert low.load_manifest(MANIFEST) == low.EXPECTED_MANIFEST
    assert len(low.EXPECTED_MANIFEST["variants"]) == 2
    assert low.EXPECTED_MANIFEST["authority"]["live_trading_authority"] is False
    assert low.EXPECTED_MANIFEST["authority"]["automatic_strategy_promotion"] is False
    assert low.EXPECTED_MANIFEST["execution"]["stress"] == {"fee_bps": 25.0, "slippage_bps": 15.0}
    assert low.EXPECTED_MANIFEST["evaluation"]["previously_inspected_locked_holdout_is_pristine"] is False
    for mutation in ({"automatic_strategy_promotion": True}, {"live_trading_authority": True}):
        changed = deepcopy(low.EXPECTED_MANIFEST)
        changed["authority"].update(mutation)
        path = tmp_path / "changed.json"
        path.write_text(json.dumps(changed), encoding="utf-8")
        with pytest.raises(low.LowTurnoverHypothesisError, match="manifest"):
            low.load_manifest(path)
    changed = deepcopy(low.EXPECTED_MANIFEST)
    changed["execution"]["stress"]["slippage_bps"] = 1.0
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(low.LowTurnoverHypothesisError, match="manifest"):
        low.load_manifest(path)


def test_completed_bar_targets_hold_cooldown_and_real_execution_activity() -> None:
    frame = _closed_frame()
    for config in low.EXPECTED_MANIFEST["variants"]:
        targets = low.generate_targets(frame, config)
        assert set(targets.unique()) <= {0.0, 1.0}
        starts = [i for i in range(1, len(targets)) if targets.iat[i - 1] == 0 and targets.iat[i] == 1]
        exits = [i for i in range(1, len(targets)) if targets.iat[i - 1] == 1 and targets.iat[i] == 0]
        assert starts and exits
        for start in starts:
            following = [exit_index for exit_index in exits if exit_index > start]
            if following:
                assert following[0] - start >= 6
        for exit_index in exits:
            following = [start for start in starts if start > exit_index]
            if following:
                assert following[0] - exit_index > 3
        metrics = discovery._simulate(
            frame, targets, 0, len(frame),
            low.EXPECTED_MANIFEST["execution"]["stress"],
            bars_per_year=365.0 * 6,
        )
        assert 0 < metrics["fill_count"] <= len(starts) + len(exits) + 1
        assert math.isfinite(metrics["total_return"])


def test_future_prices_cannot_change_earlier_completed_bar_signals() -> None:
    original = _closed_frame()
    changed = original.copy()
    changed.loc[135:, "close"] *= 1.45
    for config in low.EXPECTED_MANIFEST["variants"]:
        before = low.generate_targets(original, config)
        after = low.generate_targets(changed, config)
        pd.testing.assert_series_equal(before.iloc[:135], after.iloc[:135])


def test_invalid_data_and_unregistered_parameter_mining_fail_closed() -> None:
    frame = _closed_frame()
    config = low.EXPECTED_MANIFEST["variants"][0]
    with pytest.raises(low.LowTurnoverHypothesisError, match="unregistered"):
        low.generate_targets(frame, {**config, "entry_deadband": 0.009})
    with pytest.raises(low.LowTurnoverHypothesisError, match="unregistered"):
        low.generate_targets(frame, {**config, "min_hold_bars": True})
    gap = frame.drop(index=15).reset_index(drop=True)
    with pytest.raises(low.LowTurnoverHypothesisError, match="invalid or noncausal"):
        low.generate_targets(gap, config)
    bad = frame.copy()
    bad.loc[45, "close"] = float("inf")
    with pytest.raises(low.LowTurnoverHypothesisError, match="invalid or noncausal"):
        low.generate_targets(bad, config)
    future_order = frame.iloc[::-1].reset_index(drop=True)
    with pytest.raises(low.LowTurnoverHypothesisError, match="invalid or noncausal"):
        low.generate_targets(future_order, config)
