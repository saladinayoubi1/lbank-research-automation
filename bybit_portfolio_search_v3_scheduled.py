"""Compatibility adapter for scheduled portfolio research.

The authoritative cash-only execution implementation is bybit_portfolio_search_v3.
Importing this module must not overwrite canonical module functions.
"""
from __future__ import annotations

from typing import Any

import numpy as np

import bybit_portfolio_search_v3 as base


def exact_backtest(
    market: dict[str, Any],
    weights: np.ndarray,
    period: dict[str, str],
    profile: dict[str, float],
) -> dict[str, Any]:
    """Use the canonical next-open cash-funded research simulator."""
    return base.exact_backtest(market, weights, period, profile)


if __name__ == "__main__":
    raise SystemExit(base.main())
