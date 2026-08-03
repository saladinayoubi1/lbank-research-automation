# LBank Benchmark v1

This experiment is a reproducible research smoke test and venue-data suitability gate. It does not place orders and does not use profitability as the criterion for choosing an exchange.

## Inputs

The versioned manifest is `experiments/lbank_benchmark_v1.json`.

Selected research-ready series:

- `btc_usdt / minute15`
- `eth_usdt / minute15`
- `aero_usdt / hour4`
- `agt_usdt / hour4`

Strategies:

- `buy_and_hold`: constant target exposure of `1.0`;
- `sma_long_flat`: long when the 50-bar close SMA is above the 200-bar close SMA, otherwise flat.

Execution profiles:

- `frictionless`: zero fee and zero slippage;
- `conservative_research_cost`: 10 bps fee and 5 bps adverse slippage.

Signals use information through candle `t` and execute at candle `t+1` open through `backtest_engine.py`.

## Suitability policy

The venue is suitable as the primary research-data source only when all predeclared checks pass:

- at least 80% of the full 21-series universe is research-ready;
- every selected benchmark series is ready;
- every configured benchmark run succeeds;
- total duplicate timestamps are zero;
- total off-grid timestamps are zero.

Strategy returns, Sharpe-like values, and drawdowns are reported for diagnostics but are not used to approve or reject the venue. A profitable strategy cannot compensate for incomplete or invalid source data.

When the gate fails, the report recommends evaluating the configured secondary venue, currently `bybit`.

## Outputs

The workflow produces:

- `_experiment_manifest.json`
- `_benchmark.json`
- `_benchmark.md`
- `_benchmark_runs.csv`

The manifest SHA-256 is embedded in the report so results can be tied to the exact experiment configuration.

## Safety boundary

- public historical market data only;
- no private API;
- no credentials;
- no order placement;
- no automatic transition to live trading;
- no automatic acceptance of fragmented LBank series.
