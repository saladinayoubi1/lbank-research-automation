# Bybit Prospective Paper Forward v1

## Purpose

This lane collects genuinely prospective Paper evidence for the frozen
`bybit_btc_eth_regime_consensus_v1` strategy. It starts no earlier than
`2026-08-26T00:00:00Z`, after the qualifying neighborhood and derivatives
validation runs recorded in the manifest.

The lane is Research / Backtest / Paper only. It uses public Bybit market
endpoints, never accepts private credentials, never places an exchange order,
and cannot enable or automatically promote Live trading.

## Frozen contract

- Strategy parameters are read from
  `experiments/bybit_frozen_regime_strategy_v1.json` and bound by SHA-256.
- Signals use completed Spot 4-hour candles and execute on the next completed
  linear-perpetual 4-hour interval, avoiding look-ahead.
- Conservative and stress profiles run as separate Paper accounts.
- Actual public funding, instrument specifications, risk tiers, minute VWAP,
  fees, margin, liquidation, and fallback slippage are recorded.
- State and per-bar events are canonical-JSON digest protected and chained.
- A workflow run ID must advance and observations must be strictly ordered.

## Resumable workflow

`.github/workflows/bybit_prospective_paper_forward_v1.yml` polls every two
hours, on manual dispatch, and when the implementation or frozen contract is
merged to `main`. The redundant poll cadence tolerates a delayed or dropped
GitHub scheduled event; it does not accelerate the 4-hour evidence clock because
the engine accepts only previously unseen completed bars. It restores the newest 90-day state artifact,
verifies the state, advances only newly completed bars, enforces Paper-only
authority, and uploads a replacement state artifact. Concurrency prevents two
writers from advancing the same chain simultaneously.

Pull requests run only the focused contract tests; they do not collect market
observations.

## Independent gate reporting

`.github/workflows/nexus_bybit_paper_gate_report.yml` observes completed
main-branch Paper workflow runs without becoming a state writer. It downloads
the exact run artifact, independently verifies the canonical state digest,
event chain, source SHA, workflow run ID, artifact identity, and fixed
Paper-only authority, then adds or refreshes Issue #984 evidence only at daily
six-bar checkpoints or terminal states.

Non-successful producer runs are recorded as fail-closed evidence. Stable
checkpoint markers prevent repeated no-new-bar runs from creating duplicate
comments. The reporter has issue-comment authority only; it cannot mutate the
Paper state, repository contents, strategy, Risk decision, or Live boundary.

## Completion boundary

The collection gate requires at least 30 elapsed days and 180 completed
4-hour bars. Both execution profiles must satisfy their locked return,
drawdown, fill, funding, execution, margin, and risk-tier gates with zero
margin rejections and zero liquidations.

Passing produces `COMPLETE_REVIEW_REQUIRED`, not Live authorization. Failing
produces `QUARANTINED`. Either result requires a separate owner review and
cannot change the project boundary automatically.

## Local verification

```bash
python -m pytest -q tests/test_bybit_prospective_paper_forward_v1.py
```
