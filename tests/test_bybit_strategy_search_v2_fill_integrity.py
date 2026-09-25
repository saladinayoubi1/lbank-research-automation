"""Fractional v2 overlay must not count unchanged positions as new fills."""
from __future__ import annotations

import pandas as pd
import pytest

from bybit_strategy_search_v2 import SearchError, approx, exact


PERIOD = {"start": "2020-01-01", "end": "2020-02-01"}


def _frame(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=len(prices), freq="4h", tz="UTC"),
        "open": prices,
        "close": prices,
    })


def _exact(prices: list[float], targets: list[float], *, fee: float = 10.0, slip: float = 5.0) -> dict:
    return exact(_frame(prices), pd.Series(targets), PERIOD, {
        "initial_cash": 10_000.0, "fee_bps": fee, "slippage_bps": slip,
    })


def test_static_full_target_matches_approximate_fill_count_without_debt() -> None:
    frame = _frame([100.0] * 100)
    targets = pd.Series([1.0] * 100)
    assert approx(frame, targets, PERIOD, 15.0)["fill_count"] == 2
    for fee, slip in ((10.0, 5.0), (25.0, 15.0)):
        result = _exact([100.0] * 100, [1.0] * 100, fee=fee, slip=slip)
        assert result["fill_count"] == 2
        assert result["total_return"] < 0.0


def test_fractional_quantized_target_changes_only_trade_at_transitions() -> None:
    # Three weight transitions followed by a flat exit: no interim drift fills.
    targets = [0.5] * 20 + [0.75] * 20 + [0.5] * 20 + [0.0] * 40
    result = _exact([100.0] * 100, targets, fee=0.0, slip=0.0)
    assert result["fill_count"] == 4
    assert result["turnover"] == pytest.approx(1.5)
    assert result["total_return"] == pytest.approx(0.0)
    assert approx(_frame([100.0] * 100), pd.Series(targets), PERIOD, 0.0)["fill_count"] == 4


def test_next_open_excludes_previous_close_to_open_gap() -> None:
    prices = [100.0, 100.0] + [120.0] * 48
    targets = [0.0, 1.0] + [1.0] * 48
    result = _exact(prices, targets, fee=0.0, slip=0.0)
    assert result["fill_count"] == 2
    assert result["total_return"] == pytest.approx(0.0)


def test_flat_target_has_no_execution() -> None:
    result = _exact([100.0] * 60, [0.0] * 60)
    assert result["fill_count"] == 0
    assert result["total_return"] == pytest.approx(0.0)


@pytest.mark.parametrize("invalid", [-0.1, 1.1, float("nan")])
def test_exact_rejects_invalid_fractional_targets(invalid: float) -> None:
    targets = [0.5] * 40
    targets[7] = invalid
    with pytest.raises(SearchError, match="fractional"):
        _exact([100.0] * 40, targets)


def test_unchanged_fractional_target_does_not_rebalance_every_bar() -> None:
    result = _exact([100.0] * 100, [0.5] * 100, fee=25.0, slip=15.0)
    assert result["fill_count"] == 2
    assert 0.9 < result["turnover"] < 1.1
