# NEXUS Regime Strategy Selector v1

## Purpose

This component lets NEXUS change the active **Paper strategy mix** when the
verified market regime changes. It is deliberately not a single-strategy
switch and it is not an execution engine.

The selector consumes:

- digest-protected `15m`, `1h`, and `4h` cross-timeframe context;
- immutable lifecycle and health evidence for independently qualified Paper
  strategies;
- the frozen policy in `config/nexus-regime-strategy-policy-v1.json`.

It produces a deterministic, digest-protected allocation proposal. Every
actual Paper action must still pass Decision and Deterministic Risk.

## Default regime policy

| Cross-timeframe alignment | Momentum | Trend breakout | Mean reversion | Cash |
|---|---:|---:|---:|---:|
| `TREND_UP` | 45% | 45% | 10% | remainder |
| `TREND_DOWN` | 35% | 55% | 10% | remainder |
| `RANGE` | 15% | 10% | 75% | remainder |
| `HIGH_VOLATILITY` | 0% | 0% | 0% | 100% |
| `MIXED` | 0% | 0% | 0% | 100% |

Low context confidence or thin liquidity also forces 100% cash. A strategy in
`WATCH` receives a 50% haircut. `DEGRADED`, `QUARANTINED`, non-Paper, missing,
or unapproved strategies receive zero weight, and their unused weight remains
cash instead of being silently redistributed.

## Evidence and authority boundary

- Existing prospective 4-hour evidence is not changed or reset.
- Each strategy keeps its own isolated Paper account and evidence chain.
- The selector cannot promote a Candidate into Paper.
- The selector cannot place an order.
- Live authority and automatic promotion remain false.
- Deterministic Risk remains final.
- Any schema, digest, freshness, health, lifecycle, or authority ambiguity
  fails closed.

## Testing

```bash
python -m pytest -q tests/test_nexus_regime_strategy_selector.py
```
