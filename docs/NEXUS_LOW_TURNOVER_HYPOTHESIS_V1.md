# NEXUS low-turnover 4h hypothesis v1 — preregistered engineering only

Status: **no strategy candidate, no eligible Paper admission, no real trading**. This is a
strict two-configuration signal prototype; its verification tests are synthetic,
not evidence of returns or a new untouched holdout. Tracking issue: #1811.

## Why a distinct hypothesis

The corrected full official MTF replay on main produced nine research cells,
zero base/refined proposals, and failed cost-adjusted risk/performance gates.
Already-inspected historical holdout and the completed failed #984 prospective
window are development context, **never** pristine validation. Repeating the
same exhausted grid or increasing trade counts is not evidence of edge.

## Frozen engineering grid

Bybit public spot research: BTCUSDT and ETHUSDT, 4h completed candles,
long/flat only, next-open execution using the independently corrected simulator.
The exact JSON manifest permits only these two alternatives:

| Alternative | Momentum lookback | Completed-close entry deadband | Minimum hold | Exit cooldown |
|---|---:|---:|---:|---:|
| A | 20 bars | 1.0% | 6 bars | 3 bars |
| B | 40 bars | 1.5% | 6 bars | 3 bars |

No parameter mining, extra variants, adaptive deadband, position averaging, or
unbounded intrabar signals. Exit when completed-bar momentum falls to zero or
below, but only after the minimum hold. Cooldown begins at the exit signal.

The stress profile is 25-bp fees plus 15-bp adverse slippage per leg:
the nominal round-trip cost floor is 80 bps, below either deadband. This does
**not** establish that the momentum measurement predicts a tradable gain.
The conservative profile remains 10-bp fees plus 5-bp slippage per leg.
All unchanged deterministic risk and funding/execution challenges still apply.

## Temporal firewall and falsification

1. Engineering uses already-inspected **training-only** data and synthetic
   fixtures. Preserve all observed old holdout/prospective artifacts unmodified.
2. Freeze this manifest, implementation, tests, exact source SHA and data
   provenance before collecting any new independent closed-candle holdout.
   The earliest possible new holdout is 2026-09-26 00:00 UTC **and** it must
   be strictly after source freeze. No old holdout becomes pristine by renaming.
3. Refuse admission if either execution profile fails fixed net performance,
   drawdown, Sharpe or actual fill-count checks. Record every inspected option,
   training-window result and explicit no-candidate decision; don't tune to
   observed validation outcomes. The separate new prospective activity minimum
   is four real simulated fills **per profile**; the old #984 locked 3/4
   QUARANTINED result must never be edited or carried forward as proof.
4. Before any future prospective Paper, separately validate perpetual
   contract specifics, funding timestamps/sign changes, executable bid/ask,
   margin and liquidation. Spot-only prototype performance is not futures
   execution proof. A distinct real-time observation starts only if every
   prior research and independent validation gate passes review.

## Current deliverable boundary

The committed code only validates the frozen manifest and generates causal
completed-bar long/flat target series with six-bar minimum holds and three-bar
cooldown. Synthetic regression tests include future-price mutation, malformed
4h data, attempts to broaden parameters, and cost-aware next-open execution
through the corrected existing simulator. It does not fetch new data, fit a
strategy, select a candidate, dispatch a Paper run, or touch a real exchange.

The user-facing owner desktop **manual Paper wallet** separately starts with
500 USDT under #1819. Published historical research and the failed immutable
prospective experiment retain their exact originally committed 10,000-USDT
initial-capital assumptions and are not retrospectively rescaled.
