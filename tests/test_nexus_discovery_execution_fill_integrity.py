"""Regression tests: discovery execution counts signals, not fee-funded dust."""
from __future__ import annotations

import pandas as pd
import pytest

import nexus_multitimeframe_strategy_discovery as discovery


def _frame(prices: list[float]) -> pd.DataFrame:
    return pd.DataFrame({"open": prices, "close": prices})


def _run(prices: list[float], targets: list[float], *, fee: float = 10.0, slippage: float = 5.0) -> dict:
    return discovery._simulate(
        _frame(prices),
        pd.Series(targets),
        0,
        len(prices),
        {"fee_bps": fee, "slippage_bps": slippage},
        bars_per_year=2190.0,
    )


def test_constant_long_has_one_entry_and_one_exit_even_with_costs() -> None:
    # Previous algorithm reported six fills on this entirely flat market.
    for fee, slippage in ((10.0, 5.0), (25.0, 15.0)):
        result = _run([100.0] * 100, [1.0] * 100, fee=fee, slippage=slippage)
        assert result["fill_count"] == 2
        assert result["turnover"] < 2.0
        assert result["total_return"] < 0.0

def test_signal_transitions_not_holding_bars_determine_fills() -> None:
    targets = [1.0] * 10 + [0.0] * 10 + [1.0] * 80
    result = _run([100.0] * 100, targets, fee=0.0, slippage=0.0)
    assert result["fill_count"] == 4
    assert result["turnover"] == pytest.approx(4.0)
    assert result["total_return"] == pytest.approx(0.0)


def test_close_signal_waits_until_next_bar_open() -> None:
    prices = [100.0, 100.0] + [120.0] * 48
    targets = [0.0, 1.0] + [1.0] * 48
    # A lookahead purchase on bar 1 would earn the jump to 120.
    result = _run(prices, targets, fee=0.0, slippage=0.0)
    assert result["fill_count"] == 2
    assert result["total_return"] == pytest.approx(0.0)


def test_discovery_executor_rejects_nonbinary_targets() -> None:
    with pytest.raises(discovery.MultiTimeframeDiscoveryError, match="binary"):
        _run([100.0] * 40, [0.5] * 40)
