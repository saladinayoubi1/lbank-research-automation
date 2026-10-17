# Strategy Finder — Exact-run novelty audit (17 October 2026)

## Artifact provenance / scope

- Historical source run: [main workflow #37931223043](https://github.com/saladinayoubi1/lbank-research-automation/actions/runs/37931223043), `NEXUS multi-timeframe strategy discovery`, status `completed/success`, event `workflow_dispatch`, source commit `0e89da3170a1a9b85fbb081f8ce53a2642d87edb`.
- Exact-run artifacts: `nexus-composite-novelty-state` (GitHub ID `11616377160`, includes `novelty-ledger.json` and `research-report.json`) and `nexus-multitimeframe-search-exhaustion` (GitHub ID `11616119346`, includes `exhaustion-certificate.json`). These artifacts are from the **same** completed main workflow run, not PR results.
- `ledger_digest=f6f27cfc6b0b4f653ce06edf0796a847b89b31247e966ee9d0d6e14a447efb36`.
- `certificate_digest=918f9d3c0fffe483df6086d43737c6d7197ed85787ecf08db60214aefc5476c9`.
- Bound archive semantic SHA256 `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`.
- Audit: `scripts/nexus_strategy_frontier_novelty_audit.py` and exact source-bound output `docs/evidence/strategy-finder-ledger-triage-20261017/exact-run-37931223043-triage.json`. Digest `a7fa8595d2c797deb77d749a12da8d6d051cabafe28d8418e9e59fb75c5f18a0`. Original output file on isolated Laptop2 QA SHA256 `7cfb57f07d8c3a479cbe6259ba20ca76c1f457450605e2e8ae2ef45fae41d38a`.
- Isolated QA on Laptop2: **13/13 tests PASS**; native CLI exit 0; no laptop1 or existing runtime modification.

## Exact observed historical ledger

The prior research ledger records **21 evaluated mechanism IDs**, **103 training-screened IDs** and **32 evaluated configuration fingerprints**. These are not 21 fully qualified live systems, nor 103 independent holdout results. Its report explicitly says `EXHAUSTED_REQUIRES_NEW_MECHANISM`, `NO_NEW_CANDIDATE`.

Of the 29 existing reviewed design contracts, the exact-bound classification is:

| Exact evidence category | Count | Interpretation |
|---|---:|---|
| `ALREADY_EVALUATED` | 8 | Exact same design ID recorded in evaluated historical ledger; no further identical replay |
| `TRAINING_SCREENED` | 14 | In historical training screen, **not** equal to independently validated qualification |
| `IDENTITY_ABSENT_SEMANTIC_REVIEW_REQUIRED` | 4 | Catalog ID absent from ledger; may be a semantic alias of older reviewed mechanism; not automatically new |
| `INPUT_PROOF_REQUIRED` | 3 | Signed trade flow, Spot L2 and Perpetual funding/open interest lack globally attested input proof for this certificate |
| **Total** | **29** | None now has new executable / Paper / Live authority |

The four ID-absent contracts and illustrative *possible* overlaps requiring **human independent topology comparison** (not claims of identical economic backtests):

1. `multi_tf_structural_retest` ↔ `structural_pullback` (4h structure, 1h volatility, 15m retest).
2. `compression_expansion_response` ↔ `volatility_compression_expansion` (lagged compression, range breakout, relative volume), and separately rejected isolated compression PR #2702.
3. `range_failure_reversal` ↔ `failed_range_break_reversal` (failed range break / reclaim, known ranging context).
4. `cross_pair_relative_rotation` ↔ current cross-pair relative-reclaim family **only partially**. A genuine portfolio-rank-switching/rotation mechanism requires a new shared-capital, synchronized BTC/ETH state model, reallocation cost and a distinct exit/risk contract. Do not represent the existing per-symbol long/flat peer confirmation as verified portfolio rotation.

**No novel strategy is thereby proven.** A named catalog row, training screen, successful workflow, or changed fingerprint cannot qualify or cause Demo entry.

## Next exact bounded research experiment

Priority for *new technical implementation review* is **shared-collateral BTC/ETH cross-pair regime-aware relative rotation**, precisely because it is potentially a different execution topology than the legacy single-symbol long/flat per-symbol engine. This is a *design to falsify*, not an approved strategy.

Prerequisite: independent semantic topology comparison against archived older portfolio search and composite results, not just matching IDs. Before any replay freeze actual next-open / cross-pair lag and rank switch, cash shared-account (initial simulated 500 USDT as a research benchmark only), no implicit short, max gross exposure ≤100%, explicit simultaneous sell-before-buy cash rules, no overlapping budgets, stale/missing candle rejection, BTC/ETH exact UTC alignment, transaction fees/slippage on *both* legs, and 60/20/20 temporal training/validation/already-inspected historical test separation. Must not claim uninspected out-of-sample from these archives. Publish monthly trade count, net P/L, mean P/L, drawdown, stress, and objective rejection if unprofitable. No arbitrary minimum trade-count gate.

The alternative signed-flow/L2/perpetual families **must stay DATA_BLOCKED** until independently verified point-in-time datasets are available. No external data provenance is invented.

## Safety and boundary

Research/Backtest/Paper only, Bybit primary; official already-inspected historical datasets are exploratory. The owner Laptop1 Demo, installations, journal, profile, runner and 500 USDT reference balance remain unchanged. **Live=false**, no automatic qualification, promotion, dispatch or orders from this audit.

Execution of future candidate work should be supervised by existing NEXUS Research Agent and Independent QA (issue #2007), not a parallel runtime or new speculative auto-dispatcher.
