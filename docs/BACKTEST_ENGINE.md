# Backtest Engine Core

## Scope

`backtest_engine.py` is a pure, strategy-neutral, single-series execution and accounting engine. It does not generate signals and cannot place exchange orders.

The caller supplies one target exposure for every candle. A target exposure represents desired signed notional divided by current equity:

- `1.0`: fully long;
- `0.0`: flat;
- `-1.0`: fully short;
- intermediate values: partial exposure.

The configured `max_abs_exposure` is enforced without silent clipping.

## Timing contract

A target calculated for candle `t` is executed at candle `t+1` open.

```text
completed candle t
        ↓
target exposure for t
        ↓
execution at candle t+1 open
```

Consequences:

- no execution occurs on the first candle;
- the final target is ignored because no next candle exists;
- a strategy must calculate each target using only information available by the close of its signal candle.

This shift is enforced by the engine to prevent same-candle look-ahead execution.

## Execution model

At each executable candle open:

1. Equity is marked using the opening price.
2. Desired quantity is derived from target exposure and opening equity.
3. The difference from current quantity is filled at the opening reference price plus adverse slippage.
4. Fees are charged on absolute filled notional.
5. Equity is marked at candle close.

Slippage is adverse on each side:

- buys fill above the reference price;
- sells fill below the reference price.

Fee and slippage inputs are expressed in basis points.

## Cash and short accounting

The engine uses signed quantity and cash accounting:

```text
equity = cash + position_quantity × mark_price
```

Selling short increases cash and creates a negative quantity. Buying to cover reduces cash. This is a research abstraction, not a complete exchange margin model.

## End-of-test handling

By default, an open position is liquidated at the final candle close with the configured fee and slippage. Set `liquidate_at_end=False` to retain an open mark-to-market position in the final result.

## Outputs

`BacktestResult` contains:

- `equity_curve`: candle-level cash, quantity, equity, exposure, and drawdown;
- `fills`: each rebalance and optional final liquidation;
- `metrics`: final equity, net PnL, return, maximum drawdown, fees, turnover, exposure, bars, and fill count.

Maximum drawdown is reported as a positive magnitude in `metrics`; the equity-curve `drawdown` column contains non-positive values.

## Required data path

Production research code should load candles through `research_data.load_research_series()` before constructing targets. That loader enforces readiness, canonical schema, series identity, and timestamp integrity.

## Explicitly not modeled in this phase

- exchange order-book depth;
- partial fills or rejected orders;
- perpetual funding;
- maintenance margin or liquidation;
- borrow availability or borrow cost;
- intrabar stop/target sequencing;
- multi-asset portfolio netting;
- strategy signals or parameter optimization;
- real trading or private API calls.

Those features require separate, versioned extensions and focused tests. They must not be silently approximated in the core engine.
