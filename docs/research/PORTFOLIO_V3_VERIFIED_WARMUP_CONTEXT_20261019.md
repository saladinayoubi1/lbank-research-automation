# Connect verified historical warmup to the fixed portfolio engine

The approved 79-day source extension was complete, but the original engine still
loaded only the archive ending2026-07-31. The new opt-in context command joins
the already verified 474 closed4h bars per asset to the original 8034 rows and
feeds the resulting 8508-row market to the unchanged engine's feature and target
functions. It never invokes a financial backtest or an execution/Manager API.

This is a bounded DATA-20/DATA-21/RES-32/QA-41 context connection. It preserves
the completed Phase 7 boundaries and uses the existing fixed-system handoff;
it does not create a second trading pipeline or change strategy parameters.

## Exact input and trust boundary

`research/portfolio_v3_warmup_context_v1.json` pins the capture and independent
Decimal QA digests already verified in merged PR #2752. The existing handoff,
engine, calibration, future freeze, V5 preflight and source-verifier code are
hash checked. Every run rehashes all six original Parquets, all 158 retained
raw gzip files and all 158 daily receipts. It consumes the prior complete
70,815,420-tick Decimal audit rather than recomputing that completed study.
A rehashed replacement QA receipt cannot inherit the reviewed digest.

The join requires the exact paired UTC grid from 2022-12-01 through 2026-10-19
exclusive, physical positive OHLCV and an intact source seam. It neither
sorts malformed warmup data into acceptance nor fills missing bars. Files at
or beyond the frozen score start cannot enter this context operation.

## Causal features and original review phase

The command calls only the original market loader, candidate identity,
structural-state, realized-volatility, target and review-mask functions.
Appending warmup must preserve all 8034 original price rows and every original
score, eligibility, volatility and target value, including missing states.
The unchanged 30/90/180-day candidate remains `b4e4a2c33304aec1`.

The 42-bar cadence remains anchored at 2022-12-01, not restarted on August 1.
The first warmup review is 30 bars after that seam; resetting the calendar
there would change the system. The next review source bar opens 2026-10-22
at 00:00UTC and is observed only when it closes at 04:00UTC. These are review
times, not an order or a promise of a fill. The last closed context target
is explicitly advisory and grants no execution authority.

## Reusable context and reproduction

Run from a normal checkout with the locked dependencies:

```sh
python -m unittest discover -s tests -p test_nexus_portfolio_v3_warmup_context.py -v
python -m scripts.nexus_portfolio_v3_warmup_context --capture-root <existing-capture-results> --archive-root <original-archive> --output <new-isolated-context-directory>
```

The write-once directory contains `joined-market-4h.npz` and`context.json`.
`load_market_bundle(path, recorded_sha256)` rechecks the bundle and restores
the exact ordinary engine market structure, with no pickle or inferred data.
The producer verifies that round trip. No original Parquet, capture receipt,
owner installation, profile or Paper journal is overwritten.

Eleven focused synthetic test methods cover altered frozen inputs, source
bytes and rehashed receipts; missing/future/naive/invalid bars; preserved
prefixes; the global calendar; bundle tampering; write-once behavior; and
the absence of calls to the financial engine. Native completion and exact
context/source identities are recorded separately in the physical receipt.

## Verified physical completion

Laptop2 completed all 11 tests and the real context preparation with native
exit 0. All six original Parquets, 158 raw gzip days and 158 daily receipts
matched their approved identities. The resulting paired context has 8508
rows per asset; all 8034 original price/feature/target rows were preserved.
The NPZ round trip passed. The separate Decimal tick study was not rerun.

Context digest:
`bd3b57243c7ac5c6ed017b8840df77f4d1bec519a1449e964bb3b4e27e6bc3d3`.
The exact result and code/test/log bindings are in
`docs/evidence/portfolio-warmup-context-20261019/context.json` and
`verification.json`. The native bundle remains in the isolated context
directory recorded there; raw source and owner state remain unchanged.

## macOS fixture portability correction

The first hosted macOS test execution reported four fixture errors because
its temporary paths used the system `/var` alias. The intentional production
guard rejects symlink ancestors. Test-created directories are now resolved
to their physical path before use; the production script and guards are
byte-identical. A local `var -> private-var` fixture reproduced the same four
errors before the correction, then all 11 methods passed. An explicit aliased
source path still fails the unchanged production guard.

`portability-review.json` records that reproduction and the corrected test
hash. The original physical receipt still attests its original test hash
and unchanged runtime; no physical context or financial study was rerun.
Fresh hosted macOS validation is required before merge.

## Remaining authority boundary

This prepares historical input, not a backtest, edge, formal independent
signal/financial QA, future-source authorization or a dispatched Research
worker. The existing BLOCKED Manager task stays unchanged. The separately
reviewed raw-archive future-source policy and exact financial Research/QA
executor handoff are still required. The full 2026-10-19..2027-01-17 frozen
horizon, V5-only preflight, other frozen studies and rejected hypotheses
remain intact. No data is downloaded, no schedule/monitor is created and
Live=false; Paper eligibility=false; orders=0.
