# Bybit BTC/ETH Regime Consensus v1

## Decision

The frozen four-component regime-consensus ensemble is eligible for a separate derivatives-data validation and prospective paper-forward phase. It is not approved for live trading.

## Dataset

- Official public Bybit Spot archives only.
- BTCUSDT and ETHUSDT.
- 4-hour candles.
- Historical range: 2022-12-01 through 2026-07-31 UTC.
- Immutable archive SHA-256: `5f1173467c2296201940c3b7786b7cc3e5442244e07289769ab4867ace41d668`.
- Six source series passed strict timestamp, OHLC, row-count, identity and snapshot-hash checks.

## Strategy

Signals are calculated only from completed 4-hour candles and executed at the next 4-hour open.

Each asset uses:

- time-series momentum over 30, 90 and 180 days;
- 45-day versus 240-day exponential moving-average confirmation;
- a 3% momentum deadband;
- long approval when at least half of the momentum horizons are positive;
- short approval when at least two thirds are negative;
- a 30-day fast-reversal veto.

The broad BTC/ETH regime is classified with 30-day fast momentum and 120-day slow momentum:

- **Bull:** long consensus is permitted.
- **Bear:** short consensus is permitted only after both fast and slow broad momentum are negative.
- **Transition:** short exposure is disabled and qualifying long exposure is reduced to 25% of its normal size.

Position sizing uses inverse volatility, a 10% annualized target-volatility ceiling, a 90-day volatility estimate and weekly target changes. When 14-day volatility exceeds 1.25 times the 90-day estimate, target exposure is halved. Weights are quantized in 10-percentage-point increments and gross exposure cannot exceed 100%.

The frozen ensemble takes the median target weight from four components. They differ only in regime threshold (`0%` or `3%`) and short scale (`25%` or `50%`).

## Historical cross-validation

Seven chronological folds were evaluated with next-open execution. Parameters were frozen before the local-neighborhood validation.

| Metric | Conservative | Stress |
|---|---:|---:|
| Fee per fill | 10 bps | 15 bps |
| Adverse slippage | 5 bps | 10 bps |
| Annual short carry | 20% | 40% |
| Positive folds | 6 / 7 | 6 / 7 |
| Median fold return | 4.18% | 3.60% |
| Worst fold return | -1.34% | -1.60% |
| Worst fold drawdown | 4.64% | 4.64% |
| Median fold Sharpe-like ratio | 0.93 | 0.81 |
| Minimum fold Sharpe-like ratio | -0.44 | -0.54 |

All predeclared conservative and stress gates passed.

## Parameter plateau

A frozen-strategy neighborhood of 480 candidates was tested without reselecting the frozen strategy from those results. Twenty-nine neighboring configurations passed both cost profiles. Passing configurations covered:

- two distinct momentum lookback sets;
- two distinct EMA pairs;
- target volatility values of 10% and 11%.

This satisfies the predeclared plateau requirement and reduces the likelihood that the selected result is an isolated parameter spike.

## Research boundary

All available historical data has now informed development. The results are therefore historical cross-validation and sensitivity evidence, not a pristine out-of-sample proof and not a guarantee of future profit.

Before prospective paper forward:

1. validate actual perpetual-futures funding, margin, liquidation and symbol specifications;
2. validate next-open execution assumptions against executable bid/ask data;
3. freeze all strategy and risk parameters exactly as versioned;
4. run a prospective paper-forward period without parameter changes;
5. require a separate promotion decision after that forward evidence.

No private API, credentials, orders, withdrawals or live-trading activation are included.
