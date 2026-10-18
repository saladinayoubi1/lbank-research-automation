# V119 recorded entries: independent closed-prefix compatibility evidence

All **77 unique previously recorded entries** have exactly one compatible
pre-entry structural witness under V119's unchanged rules: training 42,
inspected validation 19, inspected historical test 16. The two cost profiles
represent these same paths, not 154 independent entries. No incompatible or
multiple-witness entry was found in this fixed ledger.

This reduces uncertainty about the timing and geometry of the recorded entries.
It does not make the rejected strategy profitable or establish original signal
emission, complete discovery coverage or full Elliott wave counting.

## Method and boundaries

`nexus_elliott_v119_entry_witness_qa.py` is separate from the strategy engine.
It reads only the bounded closed-bar prefix needed to check each **fixed recorded
entry**, preserving every strict pivot event, including adjacent same-kind
events. It checks three consecutive LOW/HIGH/LOW pivots, center+3 confirmation,
frozen geometry and horizon, unbroken support, the first retest/reclaim and the
recorded bracket. It does not choose a preferred witness if several are possible.

The earliest possible Wave0 center is derived from the frozen pattern span,
right confirmation and retest horizon. Its left neighbors are included. For the
current parameters this requires at most 184 pre-entry bars. The decision-witness
function never reads the entry bar or later prices. Entry mid comes from the
unchanged ledger; the previous independent accounting audit already matched that
mid to the physical next open. Confirmation availability is the source bar open
plus 15 minutes, not the pivot's retrospectively recognized center time.

The CLI reads the complete immutable archive only for input identity/grid checks
and supplies it to the bounded checker. No market backtest, economic result,
candidate ranking, new entry or whole signal-universe replay was performed.
Original raw result, engine, accounting QA, six financial rows and rejection
remain unchanged. Each reconstructed witness records its source indices,
availability timestamps, prices and closed-prefix digest.

## Immutable evidence

- Checker committed **before** the physical check: `1a94d56dbfc9623d7a0b6776ff50e8196c0a24f3`.
- Exact checker SHA256: `22d8b83982ee5248628a009209e84cd8039207ad8438fed8e43794b520d6c2cf`.
- Original ledger raw SHA256: `46be9c744f14d73d0be391f3b164d127ef93e5bcc80f701225b34ab8838e2546`.
- Original result digest: `bd27b37d66caabfd79e7d19ad158bdf665e0efce51772167e98ea05957f90fb8`.
- Original engine SHA256: `c19d49e644fe0067e405b5cc25366f54b33d403c5445bd9dd56d7210c9de1672`.
- New witness QA digest: `9770c358544cfb53430306bba92e48816c4f2380b2a3ab208225e8ea1f7ce6ae`.
- New artifact: `product_ui/research-reports/elliott-v119-entry-witness-qa.json`.
- BTC archive SHA256: `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`.
- ETH archive SHA256: `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`.

Laptop2 ran the byte-verified checker in the isolated
`E:\NEXUS-QA\elliott-entry-witness-20261018` directory against the original
ledger and the existing `C:\NEXUS\research-cache\replay-canonical-37681826492\archive\bybit_market`
cache. It exited 0 with 77 unique compatible witnesses. Both Bybit Spot archives
remain 128,544 aligned 15-minute bars, 2022-12-01 through 2026-07-31 UTC.

## Existing consumer and independent scope

The existing Research Reports provider pins the new QA digest, verifies exact
correspondence with the 77 ledger entries and checks witness chronology/digests,
coverage and authority. Missing/altered/self-rehashed evidence rejects only the
Elliott view. The current report UI adds the per-entry candle chain and counts.
No new service, queue, monitor or installed application was started.

**This is retrospective compatibility evidence.** The historical ledger did not
record the original emitted signal ID or pivot/retest/reclaim trace. Finding one
compatible source chain does not prove that the original process emitted that
specific event, that all 1,109 candidates were correct/complete, or that selection
priority was correct. Therefore `original_signal_event_identity_verified` and
`signal_to_entry_causality_independently_verified` remain **false**. Future actual
executions still need to record their emitted, source-bound event identities.

Disposition remains **HISTORICAL_NEGATIVE_DO_NOT_RETUNE**. The shared 500 USDT
results, missing equity drawdown and lack of pristine future validation remain
explicit. Full Elliott counting, Manager original-execution receipt, QUAL-42 and
REG-50 admission remain ungranted. Paper eligibility, automatic Demo promotion
and Live remain false; orders remain zero. V52/V101/V117 freezes were untouched.

## Validation

- 18 focused boundary tests passed before the physical check: actual strict
  pivots, ambiguous centers, preserved same-kind events, early reclaim rejection,
  support failures, exact maximum horizon/span and a guarded sequence that raises
  on any entry/future-bar read.
- Final native suite: **52 passed** across the original 17 mechanics/accounting
  tests, the report/tamper/selection tests and the new prefix tests. Bundle SHA256
  `a288e09f4e9318f44e92679277aff1cb6cf9e03139b566c2cb98f0d473a6d784`.
- Node behavior check covers the 77-entry view and its retrospective scope;
  Python compilation and JavaScript syntax pass. Required full repository checks
  run on the final PR head before normal protected merge.
