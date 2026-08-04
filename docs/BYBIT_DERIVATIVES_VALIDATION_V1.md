# Bybit Frozen Regime Strategy — Derivatives Validation v1

## Purpose

This validation keeps every signal and risk parameter in `bybit_btc_eth_regime_consensus_v1` unchanged. It replaces the simplified Spot-based short model with a USDT-linear perpetual account model and re-runs the same seven chronological folds.

## Data contract

Public Bybit V5 market endpoints are used for BTCUSDT and ETHUSDT:

- USDT-linear 4-hour trade-price candles for contract PnL;
- 4-hour Mark Price candles for valuation, margin and liquidation checks;
- 4-hour Index Price candles for basis diagnostics;
- historical funding settlements;
- current instrument specifications and risk-limit tiers;
- 1-minute USDT-linear candles around each scheduled target change.

The immutable Spot archive remains the signal source. This is intentional: changing the signal source would create a new strategy rather than validating Frozen V1.

## Corrected account model

The validator includes:

- linear-contract realized and unrealized PnL accounting;
- actual historical funding-rate cashflows with the exchange sign convention;
- quantity-step, minimum-quantity, minimum-notional and maximum-market-quantity checks;
- two-times account leverage while retaining the frozen 100% gross-exposure ceiling;
- Initial Margin and Maintenance Margin using public risk-tier parameters;
- Mark Price liquidation checks and explicit liquidation/margin-rejection gates;
- current risk-tier utilization reporting;
- forced closing costs at each fold boundary.

## Corrected execution model

Historical level-2 order-book snapshots are not exposed by the public V5 historical REST endpoints. Execution therefore uses an auditable conservative proxy:

1. retrieve official 1-minute USDT-linear candles after the next 4-hour open;
2. calculate turnover divided by volume over the first three minutes, or five minutes under stress;
3. add an adverse half-spread assumption;
4. add a participation-sensitive market-impact charge;
5. use a larger fallback penalty if the minute window is unavailable.

This is materially stricter than filling the entire order at the 4-hour open, but it is not a claim of historical level-2 replay.

## Promotion boundary

Frozen V1 qualifies for prospective paper forward only when both conservative and stress profiles pass all predeclared performance, data-coverage, margin and liquidation gates. Parameters are not reselected from the derivatives results. No private API, credentials, orders, withdrawals or live-trading activation are included.
