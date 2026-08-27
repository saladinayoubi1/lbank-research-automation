# NEXUS Multi-Timeframe Strategy Discovery v1

## Purpose

This lane expands Strategy Lab research across the same bounded Demo surface already supported by NEXUS:

- symbols: `BTCUSDT`, `ETHUSDT`
- timeframes: `minute15`, `hour1`, `hour4`
- families: `momentum`, `trend_breakout`, `mean_reversion`

It exists to find stronger preregistered variants without weakening the existing qualification, lifecycle, deterministic Risk, or Paper gates.

## Authority

The discovery lane is **Research-only** and **Paper-bounded**. It cannot:

- create a Candidate or Paper lifecycle state;
- submit an exchange order;
- use private exchange credentials;
- grant Live/L4 authority;
- automatically promote a strategy;
- modify the frozen prospective 4h evidence gate.

A successful discovery result is only a `RESEARCH_PROPOSAL` and explicitly requires independent runtime requalification before any later lifecycle transition.

## Dataset binding

The GitHub workflow restores the immutable Bybit archive and verifies the exact archive SHA-256 before extraction. The engine then independently requires:

- exact BTC/ETH symbol identity;
- exact 15m/1h/4h timeframe identity;
- exact schema;
- monotonic unique timestamps;
- gap-free cadence for each timeframe;
- exact BTC/ETH timestamp alignment within a timeframe;
- finite positive OHLC and non-negative volume.

Any mismatch fails closed.

## Leakage and selection policy

For each of the 9 family/timeframe hypotheses, the full historical series is split chronologically into a 70% training segment and a 30% locked holdout.

1. All preregistered variants are evaluated on the training segment only.
2. Variant ranking and selection use training evidence only.
3. The selected variant is then challenged once on the locked holdout under conservative and stress execution costs.
4. The locked holdout never participates in variant ranking.
5. All target generators are causal and trades use the previous completed bar target at the next bar open.

The test suite mutates locked future prices and verifies that the selected training variant does not change.

## Execution realism

The discovery simulator is long/flat only and includes:

- next-open execution;
- fees;
- slippage;
- forced liquidation at evaluation end;
- turnover;
- drawdown;
- timeframe-specific annualized Sharpe using the correct bars-per-year for 15m, 1h, and 4h.

Both conservative and stress profiles must satisfy the locked gate before a proposal is emitted.

## Output contract

The verified artifact contains:

- all 9 evaluated family/timeframe cells;
- selected training-only variant and training evidence;
- conservative/stress locked evidence;
- a digest-bound list of eligible `RESEARCH_PROPOSAL` records;
- an independent verification record;
- explicit `automatic_strategy_promotion=false` and `live_trading_authority=false` boundaries.

No proposal is treated as a qualified strategy merely because discovery found it.

## Downstream path

The intended path is:

`Discovery → RESEARCH_PROPOSAL → independent canonical runtime requalification → Candidate (only if existing qualification passes) → isolated Demo Paper → at least 5 genuinely closed Paper trades → health/drift state → regime selector proposal → Deterministic Risk`.

The frozen prospective 4h gate remains separate and unchanged.
