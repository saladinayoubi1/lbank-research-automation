# NEXUS Elliott V64 — independent 5m child-degree exploratory falsification

**Date:** 2026-10-16 UTC. **Scope:** isolated Bybit Spot BTCUSDT / ETHUSDT historical research, no orders, no Demo or Paper changes, Live disabled. Draft PR #2673. V52 frozen original prospective 15m parent / **3m child** hypothesis, study dates, source hashes and score gates remain untouched.

## Why this experiment exists — and what it cannot prove

The previously inspected, physically source-bound ETH 2026-10-10 bullish 9-parent geometry failed its V49/V50 fixed 3m child count: **six** alternating strict interior first-leg pivots instead of the **four** required for a five-segment child impulse. Rather than hiding or deleting two real pivots, V64 asks a **separate, mechanically specified** question: if the *same* 15m parent has **5m child bars** (`15/3 = 5` rather than the frozen V50 `15/5 = 3`), does the predeclared strict 1m-mapped wave witness exist?

**Critical experimental limitation:** the choice to examine 5m was made **after inspecting the historical 3m rejection**. Therefore even a hypothetical historical acceptance at 5m would NOT be independent validation or justify Demo promotion. V64 is not a preregistered part of the prospective V52 experiment. Additional future untouched data with a separately fixed evaluation protocol would be required before assigning the alternative predictive credibility.

## Source-bound model

The standalone `research/elliott_v64_alternative_5m/propose_degree_v64.py` preserves V50's independent 1m source checks, strict UTC chronology, physical parent pivot provenance, strict XOR outside-bar rejection, fixed width-1 *coarse* pivot, deterministic only-same-kind replacement, and independent V40 `5-3-5-3-5 + ABC 5-3-5` child geometry verification. It changes **only** the proposed child timeframe from 3m to **5m**, with the UTC 5m grouping/alignment and right-hand closure adjusted accordingly. It never emits an order, entry signal, P/L, or Demo eligibility.

It is **not wired into V53/V62 prospective scanner**; V52 original 3m decisions remain the only frozen score rules. V64's `source_bound_one_degree=True` on a synthetic example means structurally representable at one child degree, not an Elliott trading strategy or proof of recursive completeness.

## Historical inspected physical-data result

The isolated Laptop2 local exploratory runner reopened V48's accepted BTC/ETH parent witnesses, V45 exact hashed raw-to-minute source receipts, and V46 independent 1m oracle status, then evaluated the identical single bounded ETH parent on the complete five-day 1m historical source. The V64 corrected labeled receipt contains:

| Read-only structural finding | Original 3m V50 | Alternative 5m V64 |
|---|---:|---:|
| Verified parent candidates: BTC | 0 | 0 |
| Verified parent candidates: ETH | 1 | 1 |
| Strict coarse child pivots mapped to physical 1m (whole ETH source) | 939 | 546 |
| Ambiguous/unverified coarse pivots (whole ETH source) | 88 | 78 |
| Interior first-leg strict pivot count | **6** | **6** |
| First-leg required interior count | 4 | 4 |
| First-leg degree witness accepted | No | **No** |
| Full bounded one-child-degree Elliott proof | No | **No** |

Both methods report `DEGREE_COUNT_MISMATCH_LEG_0:required_4_interior_got_6` for the same historical ETH parent first leg. The 5m ratio alone **does not eliminate** the extra alternating reversals; selecting a different bar size solely to rescue this wave would be post-hoc overfitting.

**Historical proof:** `E:\NEXUS-QA\elliott-v64-alt-degree-20261016\V64_HISTORICAL_FIVE_MINUTE_QA.json`, exact SHA256 `cf196d248c62c66b67f5581730acca0b6d25799cac1d52b865ee262d1938f4b1`. The local, device-path-specific replay runner is `E:\NEXUS-QA\elliott-v64-alt-degree-20261016\run_real_v64.py`; it is **not installed into production or the GitHub CI runtime**. The committed pure proposer and tests are path-neutral and reproduce the underlying 5m structure on independent synthetic fixtures.

## Tests and fail-closed behavior

The independent V64 test suite `research/elliott_v64_alternative_5m/test_degree_v64.py` verifies all of the following: 5m and no-trade flags frozen within **this exploratory module**; a completely valid source-bound synthetic 5m child geometry passes with the correct `(4,2,4,2,4,4,2,4)` interior cardinalities; an in-progress/future decision close, missing 1m bar, fabricated parent price, future parent confirmation, naive UTC, off-grid shifted origin, or source-tied pivot all reject. It also verifies source-prefix invariance under added later completed 1m data and no recursive/trading capability on the accepted synthetic fixture. **11 of 11 tests passed on Laptop2 before GitHub publication.** Native discovery is `tests/test_nexus_elliott_v64_alternative.py`.

A synthetic geometry success demonstrates that the test method can accept an admissible witness. It is **not** a positive signal from BTC/ETH, nor backtest P/L.

## Decision and next step

**Decision: Do not promote this 5m variant as an Elliott strategy.** The same independent historical evidence fails both tested child degrees. Preserve V52 unchanged and require truly unseen future source evidence before changing the inference protocol; do not report actual trading profit from OHLC extrema. In future exploratory work, test whether a different *theoretical wave hierarchy* can account for all six strict, alternating interior pivots **without arbitrary omission and without fitting post-inspection outcomes**, on a separate predeclared validation window. No unattended monitoring or download is enabled by V64.
