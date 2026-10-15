# Elliott V17 — preregistered next-OPEN / stop-first prospective QA contract

**2026-10-15 — Research-only.** This is an isolated accounting/evaluation component and test suite, not a trader, exchange connector, strategy generator, running scheduler, market sample, profitable backtest, actual exchange fill or full Elliott wave classifier.

## Why this was added

- The frozen V9 three-pivot, five-swing seven-pivot and ABC v11 studies do not establish a profitable Elliott strategy. The source-bound V15 audit found **24/24 original five-swing price events** had coherent causal seven-pivot provenance, but this does not prove recursive wave degrees.
- The V16 ex-ante forensic audit of **10 independent old entry times**, under two fixed cost profiles, found a proposed correction-low stop to be approximately **2.695×** (conservative) or **2.893×** (stress) as wide as the old parent 1.5×mean-high-low stop at the median. The old inspected fills, losses and immutable source trace remain unchanged.
- Instead of tuning the same historical folds, V17 fixes the future sampling window and exit arithmetic *before* observing any new market outcome.

## Immutable protocol

The authoritative machine-readable [preregistration](../research/elliott_v17_future_evaluation_preregistration_20261015.json) fixes:

| Field | Fixed V17 contract |
|---|---|
| New prospective event decision window | **2026-10-16 00:00 UTC inclusive to 2026-11-16 00:00 UTC exclusive** |
| Pairs / market | BTCUSDT and ETHUSDT, Bybit, completed 15m OHLCV only |
| Source gate | Upstream V15 verified limited seven-pivot shape; V14 first CLOSED high-break and complete post-correction path |
| Recursive Elliott | **Not established**; V17 never labels a full 5-3-5-3-5 count |
| Hypothetical entry | Exactly next completed 15m bar OPEN, plus predeclared adverse entry slippage |
| Structural stop | Source-confirmed correction low; no ATR-proxy surrogate |
| Target | **2R** from the modeled slipped next-open entry and structural risk |
| Same-bar stop/target | **STOP FIRST**; unknown intrabar sequence is not falsely assumed profitable |
| Gapped exit through stop | Worse of STOP level and next bar OPEN |
| Favorable target gap | No improvement beyond TARGET |
| Time exit | At close of the 64th 15m bar if neither level was reached; partial sequences remain PENDING without P/L |
| Conservative friction | 10 bps fee plus 5 bps slippage on each leg |
| Stress friction | 25 bps fee plus 15 bps slippage on each leg |
| Research reference sizing | Independent 10,000 USDT cash reference, 0.1% initial stop risk budget and 10% cash cap, no borrow/leverage; **NOT the owner's 500 USDT Demo/Paper wallet** |
| Account authority | No orders, wallet/API access, Strategy Finder admission, automatic Demo, Live or VPS operations |

**Risk disclaimer:** the reference 0.1% *initial stop-level* budget is **not a worst-case loss cap**. Stop gaps plus adverse execution costs can produce larger absolute losses. The synthetic tests explicitly demonstrate this. A complete candid trade report must preserve this distinction.

## Data and accounting integrity

The additive source `nexus_elliott_prospective_exit_v17.py` exposes only a deterministic pure evaluator. It validates event ID/pair, aware UTC closed decision timing, fixed future-window boundary, first closed break geometry, three explicit upstream source-certification flags, and each 15m complete OHLC bar from the next OPEN through exit. The original source certifier remains separate and **caller-supplied eligibility booleans alone are not independent evidence**; a future source-binding wrapper must call V15 on each new event.

A submitted future bar must already be closed at the supplied observation time; gaps, changed times, duplicates, malformed prices, more than 64 bars and unapproved costs are rejected. The result includes the SHA256 digest of canonical submitted future bars, the exit price/ref, separate fees, modeled quantity, detailed net P/L and conservative bracket ordering. Full-bar high/low extrema are **not** presented as precisely executed MAE/MFE because intrabar price ordering is unknown. Pending/unfilled cases have no invented realized P/L.

## Evidence and remaining gate

- On Laptop2 `DESKTOP-F4SA4VL`, pinned Python 3.12.10, **28/28 native deterministic tests PASS**, including stop-first on same-bar ambiguity, unfavorable stop gaps, target price cap, first-next-open-only, 64-bar timeout, declined forming/future/malformed candles, no historical replay, fixed forward end date, future source hash, no order authority, exact independent Decimal fee/P&L accounting and reference sizing.
- A prior test assertion was corrected to actually present an aligned *forming second bar* (rather than an unaligned observation time); independent P/L checks now use the same 46-digit Decimal arithmetic precision with an absolute tolerance of `1e-35`. Neither change retunes cost settings, trades or prices.
- **No new actual 2026-10-16+ Bybit candles ingested** in this task, no prospective trade outcome measured and **no improvement in expectation or monthly returns claimed**. This is engineering completion of an evaluation *contract*, not scientific validation of an edge.
- The next separately reviewed objective is a hash-bound **future Bybit bar/1h/4h event source adapter and independent P/L reconciliation** with provenance, then a truly future read-only candidate observation. Candidate labels must accurately distinguish limited seven-pivot shape vs recursive Elliott count, and no Paper/Demo promotion occurs without independent economic acceptance.

**NEXUS architecture:** DATA-20/21 raw completed Bybit inputs → RES-31/32 source-bound V15/V14 review → VAL-40 prospective V17 research-only arithmetic → QA-41 independent provenance and accounting evidence. No link to REG-50, RUNTIME-60, PAPER-62, UI-70. Laptop1 remains sole Paper writer and existing installed app intact. VPS remains paused.

**Rollback:** remove isolated V17 source/tests and preregistration files from this Draft PR; parent strategy backtest files and all old research archives stay byte-unchanged.
