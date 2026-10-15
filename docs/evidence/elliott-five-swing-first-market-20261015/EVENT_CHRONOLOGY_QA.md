# Independent Elliott five-swing price-event chronology & signal-denial audit

**Date:** 2026-10-15 UTC. **Disposition:** `PASS` for the narrow raw-candle/event/entry/exit chronology contract; **NOT qualified for Demo**. No new market producer, new signal, strategy retuning, paper/live trading, owner journal change, VPS or runner repair was performed.

## Locked sources and physical evidence

- Research computational SHA: `5eed07d9aeb1b425fdacb868ee352b8ff36e3345`; research PR #2661 remains an unmerged Draft.
- Independent read-only Python audit on isolated LAPTOP2, `DESKTOP-F4SA4VL`: `E:\NEXUS-QA\elliott-event-chronology-audit-20261015\audit.py`. Immutable audit output: `event-chronology-review.json` alongside this report in GitHub and on LAPTOP2.
- Original 12-cell market report SHA-256: `02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc`; actual fill trace SHA-256: `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`.
- Independent audit artifact SHA-256: `6fc9f197e0aa8c049b3be948aea66595e10b80e34c9849e3d9d0c50bcc0e7fc3`.
- Archive semantic identity: `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`; all six bound archive raw-file SHA-256 identities and manifest checked **before and after** review. Original v9 terminal ledger's byte identity unchanged.

## Observed activity (one unique fee-independent signal path)

| Asset | Historical partition | First price events | Admitted next-open entries | Rejected |
|---|---|---:|---:|---:|
| BTCUSDT | Train | 6 | 1 | 5 |
| BTCUSDT | Validation | 5 | 1 | 4 |
| BTCUSDT | Previously inspected test | 0 | 0 | 0 |
| ETHUSDT | Train | 6 | 4 | 2 |
| ETHUSDT | Validation | 4 | 3 | 1 |
| ETHUSDT | Previously inspected test | 3 | 1 | 2 |
| **Unique total** | | **24** | **10** | **14** |

The same underlying event IDs were observed independently under both fixed cost profiles, giving 48 event records and 20 closed trade records across both profiles. No change to the fixed decision-time stress screening occurred between profiles.

For the **14 rejected events**, the traced denial-field counts are: **9** missing `h1_vol_ok`, **8** missing `elliott5_cost_feasible`, and **1** missing `h4_up`. These are **overlapping reasons**, so counts sum to 18 rather than 14. Observed reason counts reflect this fixed archive/signal configuration; they do not establish what would happen under modified filters.

## Verification performed

1. Independently read the immutable raw Bybit OHLC parquet archive, with a continuous 15-minute chronology and matching symbol identity. No automatic strategy engine function was imported or rerun.
2. Matched every recorded event's bar index, UTC OPEN and decision CLOSE to the matching raw candle and to a closed, never-forming 15-minute decision.
3. Verified recorded Elliott origin / first-pivot / second-pivot and confirmation indices precede the decision; fresh price-event identity is at the decision bar.
4. For every observed fill, checked next-candle **actual raw OPEN**, preserved partition bounds and opening/closing UTC times.
5. For all recorded exits, independently matched raw high/low/close, stop-first ordering (including adverse opening gaps), target, 64-bar timeout and terminal liquidation price logic.
6. Checked per-cost-profile identity equality of the same price-event geometry and raw decision inputs, and no duplicate/missing 12 diagnostic cells.
7. Confirmed the previous separate independent Decimal QA passed all fees, slipped fill prices and per-trade P&L; this audit validates chronology and is **not** a second claim of fresh strategy profitability.

All audited invariants passed; an additional **full line-by-line independent transform/market data-origin/leakage review remains open**, and this historical archive is **not** a pristine forward holdout.

## Decision and next research hypothesis

Keep `auto_demo_promotion=false`, `research_only=true`, `live_enabled=false`, sole Laptop1 Paper writer unchanged. Prior first market result remains negative in both BTC and ETH validation partitions. The dominant observable funnel losses are 1h volume-context mismatch and insufficient cost-adjusted price room, not a proven future-data timing fault.

**Next research gate:** Design a separately preregistered hypothesis about whether causal higher-timeframe volume context and the wave-pattern horizon can produce **more net-of-stress-cost opportunities**; require distinct topology/ID and untouched future prospective bars. Do not simply remove cost protections, use inspected later folds to retune parameters, replay completed v9, or promote any strategy based on these explorations alone.
