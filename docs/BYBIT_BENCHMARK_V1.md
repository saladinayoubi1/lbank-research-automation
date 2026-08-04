# Bybit Benchmark v1

This experiment is the first strategy-research phase after completion of the immutable Bybit Spot historical dataset.

## Fixed data source

- Venue: official public Bybit Spot trade archives
- Symbols: `BTCUSDT`, `ETHUSDT`
- Timeframes: 15 minutes, 1 hour, 4 hours
- Range: 2022-12-01 through 2026-07-31 UTC
- Immutable archive SHA-256: `5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668`
- Required integrity: six of six series ready; all missing, gap, duplicate, off-grid, and invalid-OHLC counters equal zero

The workflow verifies the delivery archive, per-Parquet hashes from `_snapshot_manifest.json`, row counts, identity, schema, and runtime timestamp integrity before any backtest.

## Predeclared research design

The benchmark runs fixed parameters only; it performs no parameter search or optimization.

Strategies:

1. `buy_and_hold`: market benchmark only.
2. `sma_long_flat`: 50-bar fast SMA versus 200-bar slow SMA.
3. `donchian_long_flat`: 55-bar prior-channel entry and 20-bar prior-channel exit.

Execution:

- Signals formed on completed candle `t` execute at the open of candle `t+1`.
- Long or flat only, maximum absolute exposure 1.0.
- Frictionless profile: zero fees and slippage.
- Conservative research profile: 10 bps fee and 5 bps adverse slippage per fill.
- The conservative profile is a stress assumption, not a claim about current exchange fees.

Evaluation periods:

- Full history: complete immutable range.
- Holdout: 2025-08-01 through 2026-07-31 UTC.
- Indicators may use pre-holdout history, but holdout capital starts flat.

## Paper-forward review gate

Each strategy and timeframe is evaluated across both BTC and ETH under the conservative holdout profile. It qualifies only when both symbol runs:

- complete successfully;
- have positive total return;
- have positive zero-rate Sharpe-like value;
- keep maximum drawdown at or below 25%;
- contain at least four fills;
- and the median return across the two symbols is positive.

Passing this gate does not start paper forward automatically. A separate implementation and review must still define state, scheduling, reports, and operational controls.

## Safety boundary

- No private API or credentials.
- No order placement, withdrawal, or live trading.
- No synthetic candles or source-data modification.
- No automatic promotion from historical results to paper forward.
