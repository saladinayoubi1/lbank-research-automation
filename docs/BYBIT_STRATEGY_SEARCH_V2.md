# Bybit Strategy Search v2

This phase searches a bounded, predeclared family of long/flat strategies on the immutable Bybit Spot BTCUSDT and ETHUSDT 4-hour dataset.

## Controls

- 4,320 declared configurations across EMA momentum, multi-horizon time-series momentum, Donchian breakout, and moving-average hysteresis.
- Four development folds and one locked test period.
- Selection uses only development folds.
- The selected single strategy or median ensemble is evaluated once on the locked test.
- Conservative costs are 10 bps fee plus 5 bps adverse slippage per fill.
- Stress costs are 15 bps fee plus 10 bps adverse slippage per fill.
- Qualification requires positive locked-test performance on both BTC and ETH, drawdown and Sharpe gates, development stability, and stress-cost survival.

Passing authorizes only a separate paper-forward review. It does not start paper forward, connect to private APIs, place orders, or enable live trading.
