from __future__ import annotations

import pytest

from ema_walkforward_v1 import EmaWalkForwardError, WalkForwardConfig


def test_overlapping_oos_folds_fail_closed() -> None:
    with pytest.raises(EmaWalkForwardError, match="do not overlap"):
        WalkForwardConfig(
            train_bars=300,
            test_bars=120,
            step_bars=60,
            bootstrap_samples=300,
        )


def test_non_overlapping_oos_folds_are_allowed() -> None:
    config = WalkForwardConfig(
        train_bars=300,
        test_bars=120,
        step_bars=120,
        bootstrap_samples=300,
    )
    assert config.step_bars == config.test_bars
