# Shared 500-USDT numerical diagnostic consumed by composite VAL-40

## Problem and resulting behavior

The current composite evaluator replays BTCUSDT and ETHUSDT separately with
10,000 USDT each. Those results cannot represent the owner's single shared
500-USDT cash book. The already implemented fixed shared-cash engine existed as
a standalone diagnostic, but fresh composite VAL-40 did not consume it.

New default executions emit requalification v4. They retain the original two
per-symbol screens and add one shared-book diagnostic using the same canonical
frames and the same signals captured before financial replay. The existing
engine's bytes and its fixed execution contract remain unchanged. No additional
market request, discovery search, candidate selection or parameter tuning is
introduced.

A negative shared-book cell prevents numerical review even when all four legacy
cells are positive. No shared execution is `INCONCLUSIVE`, not a measured loss.
A zero cell is likewise inconclusive; there is no minimum number of trades or
new optimizer. Legacy v1/v2/v3 artifacts remain readable with their original
accounting; the physical workflow requires v4 for new execution.

## Fixed model and evidence

- One 500-USDT BTC/ETH spot long-only book, one concurrent lot, BTC priority when
  simultaneous signals are admissible; orders resolve before the existing lot
  can exit at that open.
- Entry at the next observable open; maximum fill notional 250 USDT; maximum
  gapless stop loss including fees and slippage 2.5 USDT; quantity floored to
  eight decimals. A gap can exceed that nominal stop budget.
- `prior_range_v1`: stop 1.5 times the provided prior range below the entry fill,
  target 2R, timeout at the open 64 indices after entry; stop before target on
  ambiguous intrabar candles. Its legacy open-exit timestamp is explicitly
  retained as `open_execution_recorded_at_legacy_bar_close`.
- Fixed 60/20/20 chronological partitions, independently reset to 500 USDT;
  conservative fee/slippage 10/5 bps, stress 25/15 bps. These partitions reuse
  the already observed window and are not pristine prospective evidence.
- The new default path supports exact integer `risk_variant=0`. Variant 1 fails
  before fetching; silently substituting another exit/risk contract is forbidden.

The proof binds the candidate, exact execution source SHA, strategy-config digest,
all six canonical dataset bindings and both emitted-mask capture digests. It
retains an OHLC/range input table and all six complete trade ledgers, compactly
encoded with one common column list. Every executed lot links to its emitted
signal ID. A separate standard-library Decimal state machine reconstructs cash,
size, entries, exits, drawdown, counters, monthly sums and all cost arithmetic;
it does not call the production shared-cash engine. The stored-proof verifier
repeats that reconstruction. Small declared decimal rounding tolerances do not
replace exact trade/count/identity checks.

The existing independent-QA task contains the full v4 producer and compares it
to a complete replay at the same source/candidate/as-of. Thus input-table source
and signal authenticity still depend on that independent replay, not on a
self-issued hash. The numerical reference consumes provided range values and
captured signal masks; it does not independently derive the 15-minute indicator
or strategy equations. The existing four higher-timeframe context audits remain
mandatory.

## Bounds

This is a fixed numerical diagnostic with an explicitly different sizing and
exit model from the 10,000-USDT screen. It does not certify the exact source
strategy's complete risk and exit rules, an economic edge, pristine forward
performance, or portfolio drawdown protection (the reused model has no
portfolio drawdown kill). All owner-qualification, Paper and Live flags remain
false. A positive diagnostic permits numerical review only; existing QA,
qualification, registry and admission gates remain in force.

No frozen V52/V101/V117/V118/V119 study or completed source-system economic
study is reopened. No real market execution or device deployment is performed
for this implementation verification. Laptop2 runs synthetic code QA only.

## Verification

Native Laptop2 QA: 131 related tests passed in 53.16 seconds; after adding
capacity/fallback checks and an actual independent-QA replay, 58 focused tests
passed in 32.29 seconds. The strengthened default producer/actual-QA replay/
negative-shared-book gate integration passed separately in 30.27 seconds. A final
net-sign guard prevents rounding tolerance from changing a loss/zero into profit;
required three-OS exact-head CI covers the final source before merge.
Tests include real
production/reference comparisons, simultaneous peer conflicts, position
occupancy at exit, adverse gaps, timeout differences, reset boundaries, stop
priority, fees/slippage, no activity, re-digested corrupt evidence, legacy reads,
the actual default producer-to-verifier-to-QA path, and a 3,072-bar high-activity
v4 artifact round trip through the existing bounded transport.
