from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

import bybit_portfolio_search_v3 as base


def exact_backtest(
    market: dict[str, Any],
    weights: np.ndarray,
    period: dict[str, str],
    profile: dict[str, float],
) -> dict[str, Any]:
    """Execute only when the declared target-weight vector changes.

    Signals are still observed at candle close and executed at the next candle
    open. A held weekly/monthly target is not continuously rebalanced every
    four hours merely because market prices moved.
    """
    idx = base.period_indices(market["timestamps"], period)
    if len(idx) < 3:
        raise base.PortfolioSearchError("Period has fewer than three bars")
    opens = market["open"][idx]
    closes = market["close"][idx]
    selected = weights[idx]
    cash = float(profile["initial_cash"])
    quantity = np.zeros(opens.shape[1], dtype=float)
    fee_rate = float(profile["fee_bps"]) / 10000.0
    slippage = float(profile["slippage_bps"]) / 10000.0
    equity_rows: list[float] = []
    total_fees = 0.0
    total_notional = 0.0
    asset_fills = np.zeros(opens.shape[1], dtype=int)

    for row in range(len(idx)):
        target_changed = row == 1 or (
            row > 1
            and not np.allclose(
                selected[row - 1], selected[row - 2], rtol=0.0, atol=1e-12
            )
        )
        if row > 0 and target_changed:
            equity_at_open = cash + float(np.dot(quantity, opens[row]))
            desired_quantity = equity_at_open * selected[row - 1] / opens[row]
            changes = desired_quantity - quantity
            order = list(np.where(changes < -1e-12)[0]) + list(
                np.where(changes > 1e-12)[0]
            )
            for asset in order:
                change = float(changes[asset])
                fill = opens[row, asset] * (
                    1.0 + slippage if change > 0 else 1.0 - slippage
                )
                notional = abs(change * fill)
                fee = notional * fee_rate
                cash -= change * fill + fee
                quantity[asset] += change
                total_notional += notional
                total_fees += fee
                asset_fills[asset] += 1
        equity_rows.append(cash + float(np.dot(quantity, closes[row])))

    for asset in range(len(quantity)):
        if abs(quantity[asset]) > 1e-12:
            change = -quantity[asset]
            fill = closes[-1, asset] * (
                1.0 + slippage if change > 0 else 1.0 - slippage
            )
            notional = abs(change * fill)
            fee = notional * fee_rate
            cash -= change * fill + fee
            quantity[asset] = 0.0
            total_notional += notional
            total_fees += fee
            asset_fills[asset] += 1
    equity_rows[-1] = cash

    equity = np.asarray(equity_rows, dtype=float)
    returns = (
        pd.Series(equity)
        .pct_change()
        .replace([np.inf, -np.inf], np.nan)
        .dropna()
        .to_numpy(float)
    )
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    standard_deviation = float(np.std(returns, ddof=0)) if len(returns) else 0.0
    sharpe = (
        float(np.mean(returns) / standard_deviation * math.sqrt(base.BARS_PER_YEAR))
        if standard_deviation > 0
        else 0.0
    )
    return {
        "total_return": float(equity[-1] / profile["initial_cash"] - 1.0),
        "max_drawdown": float(-drawdown.min()),
        "sharpe": sharpe,
        "fill_count": int(asset_fills.sum()),
        "asset_fill_counts": asset_fills.tolist(),
        "turnover": float(total_notional / profile["initial_cash"]),
        "total_fees": float(total_fees),
        "average_exposure": float(np.mean(selected[:-1].sum(axis=1))),
    }


base.exact_backtest = exact_backtest


if __name__ == "__main__":
    raise SystemExit(base.main())
