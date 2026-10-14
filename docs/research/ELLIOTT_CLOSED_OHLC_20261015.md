# Elliott five-swing closed-OHLC gate — 2026-10-15

The structural helper now has a separate causal OHLC extractor and pending-setup
lifecycle in `nexus_causal_elliott_five_swing_features.py`. It emits research
price events and a fixed prospective stress-cost screen. It is not registered
in the Strategy Finder or wired to a trading consumer. A complete recursive
Elliott count, wave degree and profitability remain unproved.

The completed v9 producer is preserved and was not replayed. Its old three-pivot
wave 1–2 losses are not a market result for this new five-swing module. The v10
macro candidate remains separate. VPS work remains paused at the owner's
request; no service, recovery, authentication, pairing or Paper task is changed.

## Input and chronology

The caller supplies only completed 15-minute OHLC bars; `timestamp` means the
bar's **close**, with an explicit timezone. The extractor converts aware
timestamps to UTC and rejects missing, duplicate, reversed, gapped or unaligned
times, nonfinite/nonpositive prices and inconsistent candle ranges. It preserves
the caller's row index and input values. No forming bar or live clock is read.
The close-time convention is a caller contract, not something an OHLC value can
prove. A future engine adapter must convert archive open timestamps explicitly.

A strict extremum at index `j` becomes known at close `j+3`. Tied extrema and a
bar that is both a strict high and low are rejected because OHLC cannot resolve
their intrabar order. The latest seven accepted pivots must alternate
low/high/low/high/low/high/low. A later same-kind pivot replaces the previous
one only when more extreme. Every accepted pivot change disarms the previous
pending shape for future bars; a weaker same-kind pivot leaves it alone.

At every completed bar the extractor first reads the state stored after the
previous bar, checks invalidation/expiry and a fresh close crossing, then
processes the new pivot confirmation for the next state. The structural helper
is called with `at+1` only to prepare that next state. No event at `at` can use
the pivot newly confirmed at `at`. A break on the confirmation bar is never
backdated; any later event still requires a fresh `previous close <= fifth
high < current close` crossing.

The five preceding swings use the original fixed shape checks, 3-bar
confirmation, 192-bar origin-to-correction span, correction retracement
0.382–0.786 and 1–32-bar decision age. Diagonals, truncated fifths and
tied-shortest third swings remain outside this engineering scope. These are
prospective bounds, not a claim that every Elliott variant obeys these filters.

## Whole-path and lifecycle checks

Selected pivots alone cannot erase an unselected adverse wick. Before storing a
setup, the extractor checks all observed raw bars in these intervals:

| Condition | Completed-bar interval |
| --- | --- |
| Every later low strictly above the origin | Origin + 1 through correction confirmation |
| Inner second low is a path minimum | First high through third high, inclusive |
| Inner fourth low is a path minimum; every low strictly above first high | Third high through fifth high, inclusive |
| Parent correction low is a path minimum | Fifth high through correction confirmation, inclusive |
| Each selected inner high is a path maximum | Origin to second low; second to fourth low; fourth to parent correction, inclusive |

These inclusive whole-bar checks conservatively reject ambiguous endpoint
ranges; they do not reconstruct intrabar order or recursive subdivisions.
After storage, a touch/breach of the origin or a strictly lower parent
correction low immediately disarms the setup, before pivot confirmation. An
origin invalidation wins even when the same candle closes above the trigger.
Age 32 is eligible; age 33 expires before any crossing. Lagged metadata still
describes the previous state on an invalidation/expiry bar, so it is not itself
an eligibility flag.

The first eligible fresh close crossing consumes `(origin index, fifth-high
index)` before the cost screen, then disarms the setup. A cost denial cannot
wait for a more favorable later recross using that same identity. A newly
confirmed deeper correction can prepare a future setup only if the identity
was not consumed and every geometry/path check still passes.

## Fixed cost hypothesis

This module reuses the unchanged `stress_cost_screen` from the parent macro
module, whose signed preregistration remains byte-identical. It uses stress
fee 25 bps and slippage 15 bps **per leg**, current decision close, strictly
previous-bar 14-period mean high-minus-low range, and structural span from
origin to fifth high. The span is not the stop-risk distance.

The existing screen projects a slipped long entry, stop 1.5 ranges below entry
and target 3 ranges above it. It requires a positive stop, structural span
strictly greater than its round-trip flat-cost budget and positive projected
target proceeds after costs. The decision close is a hypothesis about the
unknown next open. Passing the screen cannot establish actual next-open fill
economics, executable liquidity, positive expectancy, body/regime admission or
a trading decision. No cost, risk or simulator rule was changed.

## Actual validation and next gate

Twenty-six new synthetic closed-OHLC tests and the sixteen unchanged structural
tests passed locally and on LAPTOP2: **42 methods, zero failures/errors**.
Native owned child PID 4028 exited 0 without timeout; the native gate took
22.80 seconds including startup/hash readbacks (test runner: 7.497 seconds).
Python 3.12.10 / numpy 2.3.5 / pandas 2.3.3 were recorded. All six staged
source/dependency hashes matched before and after execution. The four reused
files also matched their exact GitHub blobs at parent
`301462e6a362080244913b9852733e220cd61747`.

Tests include every-prefix and changed-future-tail invariance, earliest
post-confirmation crossing, no confirmation-bar backdating, wick-only breaks,
expiry, origin/correction invalidation priority, same-kind replacement versus
weaker ignored pivots, accepted-pivot disarming, tied/dual extrema, hidden raw
path violations, cost-denied identity consumption and strictly lagged range.
Synthetic cost-feasible fixtures are not profitable market simulations.

Evidence is under `docs/evidence/elliott-closed-ohlc-20261015/`: source review,
dependency readback, local/native receipts and the exact owned invocation.
The existing aggregate inventory remains 95 contracts, 122 mechanisms and
111 frontier configurations because no factory/config/engine file is changed.
The new module has no registered strategy or archive consumer; market replays
remain **0**. Live=false, no auto-Demo or failover; LAPTOP1 remains the sole
Paper writer.

The next gate is to freeze a complete new candidate contract and archive
invocation, wire this module through a close-time adapter without changing
existing approved fields, and qualify source-bound next-open fill diagnostics
before one fresh candidate evaluation. Preserve the terminal v9 ledger. Do not
replay v9 or select parameters from its already inspected Validation/final
folds; those folds are not an unseen holdout. The current work completes the
synthetic causal-feature boundary, not market or numeric qualification.

## Research adapter follow-up

A separately preregistered explicit candidate now converts canonical OPEN
timestamps through the unchanged parent decision time, preserves all old
features and feeds the shared next-open simulator with an explicit Elliott
fill-observer profile. Its 15 new tests plus the 148 previous research methods
and the pure 111-frontier schema check pass locally and on LAPTOP2. See the
[research adapter gate](ELLIOTT_BACKTEST_ADAPTER_20261015.md). The automatic
factory remains unchanged; market replay and independent market QA remain
incomplete, with Live=false and the VPS pause preserved.
