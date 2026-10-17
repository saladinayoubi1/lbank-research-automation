# NEXUS Elliott V98 — Independent physical A/B/C inner geometry, no trade promotion

**Scope:** research-only, source-locked, *retrospective* audit of exactly the same 23 July 2024 three-leg correction hypotheses in BTCUSDT (9) and ETHUSDT (14). **Not a trading backtest, complete Elliott classifier, prospective result, or performance study.** Bybit remains the only possible future Demo/Paper execution exchange; Live disabled. Laptop1 Demo, V52 2026-10-18–2026-11-15 prospective protocol, VPS and paper journal untouched. PR #2673 Draft/unmerged.

## Why a new inner A/B/C audit

V97 recorded 19 distinct three-leg intervals satisfying the **restricted outer** Zigzag price contour (BTC 7, ETH 12), and one ETH interval satisfying both restricted Zigzag and Flat price contours. This geometric contour **does not** certify a Zigzag (internal 5-3-5) or a Flat (internal 3-3-5). In V87, an earlier 1-minute strict-pivot count had already failed to establish complete lower-degree waves, but V98 independently rebuilds the *physical full-prefix terminal observations* and additionally checks each lower constituent's restrictive price geometry. No new historical rule tuning is permitted.

## Source and temporal integrity

Implementation `research/elliott_v98_correction_inner/inner_v98.py` verifies:
- Exact immutable Git blob bytes / ancestry of V97 commit `faa7ba39ecc83a65ad78c1e3ed297c80a37316b3` (V97 evidence SHA256 `672af410f645ca9e9430558dace50a1c3476a2ed62c97235b6c76f1de3320fcb`).
- V90 independently attested source-bound 3m/15m vertices and original 23 V87 A-B-C records, plus V88 pre-registration and V89 official 28 SHA-checked Binance Spot historical 1m archives (**40,320** bars). The same as-of timestamps, source ancestor chain and candidate order are preserved; the future V52 holdout is untouched.
- Independently reconstructed **all strict width=1 minute extrema** using V95's separate detector, not V86/V87's terminal detector. Every A/B/C leg's 1m full list, position, count, dual-extremum OHLC ambiguity, right-confirmation and original V87 report are compared exactly. No skipped, convenient, interpolated or retrospectively relabeled pivots.
- V97's *restricted outer* price geometry independently re-evaluated from official source and compared to each frozen V97 record, not merely trusted by name.

For Zigzag, the constituent A/B/C roles are **MOTIVE/CORRECTION/MOTIVE** with necessary counts `(4,2,4)`. For Flat, **CORRECTION/CORRECTION/MOTIVE** with counts `(2,2,4)`. Each constituent is examined independently: an exact unpruned count, strictly alternating and chronological extrema, no dual high/low OHLC minute, no future confirmation; then an explicit restricted lower-degree Impulse (motive) or Zigzag/Flat (corrective) **price-geometry** crosscheck. When several corrective families fit, no family is chosen opportunistically. These fixed-width tests are a narrow falsifiable *degree-1 hypothesis*, not a universal Elliott definition: real multi-degree waves can contain additional lower-degree or noise pivots.

## Observed outcomes on the previously inspected July sample

| Source-bound observation | BTCUSDT | ETHUSDT | Total |
|---|---:|---:|---:|
| V90/V87 original 3-leg corrective hypotheses | **9** | **14** | **23** |
| V97 restricted Zigzag **outer** price geometry pass | 7 | 12 | **19** |
| V97 restricted Flat **outer** price geometry pass | 0 | 1 | **1** |
| Entire Zigzag fixed 5-3-5 **inner** necessary-geometry gate pass | **0** | **0** | **0** |
| Entire Flat fixed 3-3-5 **inner** necessary-geometry gate pass | **0** | **0** | **0** |
| Complete recursive Elliott pattern certificates | **0** | **0** | **0** |
| New Bybit Demo orders, entries, realized P/L | 0 / 0 / none | 0 / 0 / none | 0 / 0 / none |

The V97 outer pass count is **not** a count of proven Elliott patterns and **not** 19 profitable backtested trades. The one ETH outer-family ambiguity remains unresolved and unselected. No Wave A, B, or C is promoted when its strict source-1m interior ledger or lower geometry fails. Historical evidence contains failure reasons per leg, not synthetic profit.

## QA and limitations

Software unit tests use **synthetic, clearly marked physical 1m polylines** where full 5-3-5 and 3-3-5 *necessary* grammar can pass, while market Elliott certification and trading remain false. They additionally reject altered physical wick values, future confirmations, an altered/stale V87 source ledger, source gaps, injected dual-extremum ambiguities, retroactive pruning, and forged admissibility. Actual July outcomes are assessed independently and are **never** used to tune count thresholds.

Source-local V98 report: `$env:TEMP\nexus-elliott-v98-research\V98_ABC_SOURCE_INNER_GEOMETRY.json`, SHA256 `dd6dd322ac84c80559dadc54f439ded417f1befd24b0c611310a06e4b080f490`. Published immutable copy: `docs/evidence/elliott-v98-abc-inner-20261017/V98_ABC_SOURCE_INNER_GEOMETRY.json`.

**Next independently scoped research gate:** a predeclared degree-aware pivot/noise segmentation grammar with source-backed wave placement context, calibrated and evaluated only on *untouched* data, before anyone can honestly examine cost-adjusted net returns. A positive geometric skeleton alone cannot authorize a position. No change to Demo, no Live and no merge.

## Verified QA ledger

- V98 dedicated *synthetic* lower-degree and 1m source-integrity tests: **19/19 PASS**, native `V98_DEDICATED_EXIT=0`. Covers two complete synthetic necessary-geometric family shapes, but deliberately zero trade eligibility.
- Whole existing Elliott-focused suite on Laptop2: **810/810 PASS**, `Ran 810 tests in 50.515s`, `OK`, native `V98_FULL_EXIT=0`. Locally stored log `$env:TEMP\V98_FULL_REGRESSION.txt`, SHA256 `5fc2791d9d81b09558bb429d2f77be2c7c24005ae85abac97203adfb6c23de41`.
- All 23 physical source-backed ABC cases independently replayed, exact V87/V97 record comparison, no internal fixed-width Zigzag/Flat necessary-wave acceptance. Local detailed receipt SHA256 `dd6dd322ac84c80559dadc54f439ded417f1befd24b0c611310a06e4b080f490`; copy is staged as Git binary-safe `-text` JSON.
- GitHub workflow conclusion for *new V98 commit* must be independently verified after push; local QA does not substitute for Windows/macOS/Linux CI.
