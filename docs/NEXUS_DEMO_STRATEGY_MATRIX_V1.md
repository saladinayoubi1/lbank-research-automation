# NEXUS Demo Strategy Matrix v1

## Executable Demo scope

The Demo Paper cycle runs an isolated matrix of:

- symbols: `BTCUSDT`, `ETHUSDT`;
- timeframes: `15m`, `1h`, `4h`;
- strategy families: `momentum`, `trend_breakout`, `mean_reversion`.

This produces 6 independently scheduled cells and 18 isolated Strategy Paper
lanes. A cell advances only after its next completed candle exists. Repeated
workflow invocations inside the same candle are idempotently skipped.

Each due cell executes the existing Strategy Paper Supervisor. Every family has
its own persistent Paper portfolio and evidence journal. The Supervisor ledger
must pass its independent verifier before the cell cursor advances.

## Gradual analysis

Verified cell ledgers and Paper journals are passed to the existing Paper
performance projection and drift monitor. Early results remain
`INSUFFICIENT_EVIDENCE`; health changes require the monitor's minimum closed
trade sample. Analysis failure blocks the cell and cannot silently advance its
cursor.

The read-only Demo snapshot is written to `demo/strategy-matrix.json` inside the
state artifact. It reports cell/lane status and digests without granting mutation
authority.

## Strategy discovery

The daily discovery rotation validates the existing research catalog and six
reviewed Bybit search stages, then dispatches exactly one stage per day in a
round-robin order. Its cursor is committed only after GitHub accepts the
workflow dispatch.

Discovery output never qualifies or promotes a strategy. Candidate activation
still requires deterministic validation, isolated Paper evidence, performance
monitoring, and the existing lifecycle gates.

## Authority boundary

- Research / Backtest / Paper only.
- Public market data only; private credentials are forbidden.
- Deterministic Risk remains final Paper authority.
- Automatic strategy promotion is forbidden.
- Live/L4 authority and exchange-order execution remain absent.
- The frozen 4h prospective lane remains independent and unchanged.
