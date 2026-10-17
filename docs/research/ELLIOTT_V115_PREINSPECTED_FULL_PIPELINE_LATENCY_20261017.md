# NEXUS Elliott V115 — historical full-pipeline timing and candidate-denominator research

**Source control: RESEARCH-ONLY.** V115 measures actual computational costs of the full V99 → V107/V111 → V113 pipeline using a **previously inspected** complete 14-day historical dataset, *not* the frozen future Bybit observation period. The immutable original trading constraints, installed Demo and V52 study remain untouched. No execution adapter, real order, P/L, broker authentication, Elliott-degree certification or profitability claim is introduced.

## Exact historical source identity

- Repository: `saladinayoubi1/lbank-research-automation`, branch `codex/elliott-causal-quality-research-20261015`; PR **#2673 Draft / unmerged**. V114 parent `d4152cdf9e970ce69c1f0be2b09886a20e25e4f9`, SHA256 `563ce5201a17192b7fffc70d797d5f0cacc4b31000390cd3ce867b99356f02cc`. V115 freeze checks these immutable predecessor Git bytes and the previous no-Bybit-candles/no-actual-trades state.
- Old July 1–14, 2024 UTC *Binance public Spot* historical BTCUSDT and ETHUSDT, **28 official 1-minute daily ZIPs with original downloadable checksum** and original committed V89 receipts (SHA256 `e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df`). Expected 20,160 one-minute OHLC bars per symbol, 40,320 combined.
- Original seven-field OHLC / volume / turnover rows are reconstructed from the **same historical ZIP archive bytes**, and original close and high/low bytes are cross-matched to the separately verified V99/V90 datasets before accepting any row. This is a *historical operational performance test*, NOT an independent second market feed or holdout.
- The original V101 frozen future **Bybit public Spot** period, **2026-11-16T00:00Z through 2026-11-30T00:00Z exclusive**, remains **unobserved and unavailable on October 17**, and is not used to fit a threshold or compute trading outcomes. Binance historical bars are not routed through Bybit execution or represented as Bybit observations.

## Exact measured tasks and causality

The one-run benchmark measures, in separate sections, full V89/V90 receipt checks plus independent 7-field physical source reconstruction, original unchanged V99 trailing-median **fine scale 3 and coarse scale 8** confirmed swing generation for both pairs, unpruned V107 six-consecutive-coarse-event candidate enumeration inside the complete V111 source-to-500-USDT portfolio adapter, then V113 no-sampling causal chronological event audit. It also repeats V99/V111 on the **original first 7 days** solely to verify that already mature decisions do not change when the second week of source data appears. The total includes this extra study and must not be substituted for one 14-day original source run.

The candidate census retains **all rejected / bearish / time-censored / latency-barrier-abstaining hypotheses** in its denominator. If a bullish contour survives the original frozen V106 necessary geometry and both closed reference minutes, any entry is still only a **hypothetical** V110 cash reservation. V110 uses the shared 500-USDT reference, synthetic stressed loss limits of 2.5 USDT per reservation and 5 USDT aggregate, and artificial 17bps each-side cost; a later bar closing across Wave0/Wave1 may release the *imaginary* reservation only after the event is known. This is not real trade performance, and cannot be used to claim profitability.

Benchmark timing uses `time.perf_counter_ns`; memory is Windows process **current working set and process-lifetime peak working set** measured through the operating system, not Python `tracemalloc` and not total system memory. The initial attempt with Python per-allocation tracing was explicitly aborted after excessive CPU time without a valid result; its prefinal scope manifest was archived outside Git. The final protocol disables this invasive instrumentation so the benchmark measures the original pipeline rather than a tracer. A single run does not establish statistical performance bounds. If full V111 source/candidate reconstruction dominates the run, this is a **real full-pipeline throughput bottleneck**, not a reason to prune candidates or relax the original source/timing checks.

## Artifacts and quality controls

- Module: `research/elliott_v115_historical_profile/profile_v115.py`; adversarial synthetic tests: `tests/test_nexus_elliott_v115_historical_profile.py`.
- Frozen scope: `docs/evidence/elliott-v115-old-source-full-pipeline-20261017/V115_FROZEN_OLD_SOURCE_PROFILE_RULEBOOK.json`, SHA256 `5f4947ff76bcb4888e0591940fb1346906a3808d9c804f84f4ea08043b74332a`.
- Historical output: `docs/evidence/elliott-v115-old-source-full-pipeline-20261017/V115_MEASURED_PREINSPECTED_BINANCE_FULL_PIPELINE.json`. The original result must be checked and published only if every upstream archive, minute continuity, candidate denominator, first-week causal maturity and full V113 ledger digest gate passes. **Do not replace failed evidence with estimated times or synthetic claims.**
- The study has no network fetch, no imported broker credentials, no order adapters, no modification of the original Demo, no Live Trading and no PR merge. Scientific release remains Draft until a genuinely uninspected source and separate execution assumptions are independently reviewed.

## Verified completed uninstrumented historical study — 2026-10-17

Source identity: **28 preinspected official Binance Spot 1m ZIP archives**, 14 days, BTCUSDT and ETHUSDT, **20,160 completed OHLC candles per pair**, 40,320 combined, with original V89 checksum and old committed receipt SHA matching. The immutable future Bybit period was not inspected.

| Verified full-source metric | BTCUSDT | ETHUSDT | All |
|---|---:|---:|---:|
| Source closed 1m candles | 20,160 | 20,160 | 40,320 |
| Fine causal confirmed pivots | 2,212 | 2,206 | 4,418 |
| Coarse causal confirmed pivots | 609 | 613 | 1,222 |
| All consecutive six-coarse Wave1/2 contexts | 604 | 608 | **1,212** |

**Conserved full candidate denominator:** **1,203 original necessary-contour rejects** + **4 bearish Spot-short abstentions** + **1 price-barrier touch before close-known reference** + **4 source-causal bullish reference hypotheses** = **1,212**. All **4** surviving research hypotheses received a *synthetic* 500-USDT shared-bankroll reservation, and all **4** later had a physical closed-bar barrier touch and corresponding **nonorder** release. The V110 cash journal has **8 events**, checksum SHA256 `a1cac6405de6ff892b72f08f36783bf08664e0510b8c8c9207f4c0806d6e1d95`, no end-of-source unresolved reserved cash, **zero actual orders**, null realized P/L and **zero certified Elliott waves**. A closed-bar barrier touch is NOT a filled order or profitability.

**Causal first-week safeguard:** Replaying the first 10,080 closed minutes per symbol gave **574 original six-event candidates**, one source-causal bullish research reference and one later synthetic closed-bar release. **All 574 matured candidate reference-screen records remain identical** when comparing the first-week computation to the full two-week source. No predecision candidate is allowed to be reclassified by week-two candles.

**Full V113 source timing ledger:** **2,112 mandatory checkpoints verified** with no silent sampling, exactly the **1,212 original candidate** census, **8** original cash events and matching original full ledger SHA256. This is a chronological streaming verification, not 2,112 independent full-prefix source recomputations.

## Actual performance bottleneck and measurement correction

A preliminary whole-run `tracemalloc` per-allocation instrumented attempt took over several minutes of CPU without producing complete research evidence. It was **explicitly aborted**, without market transactions; the earlier prefinal frozen scope was archived in Windows TEMP and not published. This was *measurement overhead*, so V115's final **before-commit** scope was re-frozen without the allocation tracer. The final uninstrumented one-run profile uses `time.perf_counter_ns` plus **Windows process working-set** counters (process lifetime peak), not V114's per-allocation tracing.

| Complete original pipeline segment | Measured elapsed |
|---|---:|
| Verify historical official ZIP/receipts and reconstruct 7-field OHLC | **5.642 s** |
| Both full V99 fine/coarse swing streams | **4.152 s** |
| Entire V107 six-pivot census + V111 source-to-cash replay | **19.188 s** |
| Full V113 chronological causality / source audit | **38.494 s** |
| Additional first-week V99/V111 causal-source comparison | **6.422 s** |
| **Total complete measured study** | **73.898 s** |

Operating system `Windows-10-10.0.19045-SP0`, Python `3.12.10`, Windows **process current working set 68.191 MiB**, **process-lifetime peak working set 70.602 MiB**. These are a single-run Laptop2 benchmark, not a hardware-independent bound. The **V113 proof is the largest measured single component (38.5s)** because its source-bound audit reruns the full V111 candidate construction; V113's journal-only fast timing in V114 does not include that work. A future optimization should cache source-validated candidate ledgers and verify digests against a frozen original; **do not bypass original V107 candidate enumeration, drop rejected windows, alter thresholds or reduce timing-checkpoint coverage merely to improve latency**.

Original complete frozen V115 scope SHA256 `5f4947ff76bcb4888e0591940fb1346906a3808d9c804f84f4ea08043b74332a`. Measured historical evidence SHA256 **`0889548b2b4e713e618115345e76e467f7114a8f2ed762083bf208d2f099a1e9`**; native `V115_FAST_HISTORICAL_EXIT=0`. The measured evidence is derived from repeatedly inspected July 2024 **Binance Spot**, **not Bybit**, **not a new holdout**, **not a prediction accuracy / P&L calculation**. The separate Nov 16–30 2026 Bybit public Spot prospective protocol remains untouched.

This V115 artifact is for **diagnosis and performance**, not Demo promotion, merge, Live trading, claiming four successful trades, or a guarantee of a safe stop.

## Final QA / publication checks

- **10/10 dedicated V115 tests PASS**, native `V115_UNIT_EXIT=0` before the final timing correction. They exercise cross-symbol original source contracts, full V99/V111/V113 synthetic fixture path, no future source substitutions, mature first-week invariance, tamper denial, immutable parent evidence and no order adapters.
- **1,151/1,151 entire Elliott tests PASS** *after* the final Windows working-set timing correction; `Ran 1151 tests in 64.872s`, `OK`, native `V115_FINAL_FULL_EXIT=0`. Laptop2 regression log `$env:TEMP\V115_FULL_ELLIOTT_REGRESSION_FINAL.txt` SHA256 **`facc103b90a66fdd65243c2d5f4159aabfcea7abfc3f8a4df07371878f5a2e61`**.
- Both V115 original evidence JSON files were checked to match the **exact Git-stage bytes** before commit: rulebook `5f4947ff76bcb4888e0591940fb1346906a3808d9c804f84f4ea08043b74332a`, measured historical profile `0889548b2b4e713e618115345e76e467f7114a8f2ed762083bf208d2f099a1e9`. Original 28 ZIP receipts were checked during the measured study.
- Predecessor V114 GitHub CI `Test`, `Research Evidence Refresh`, `Workflow Permissions Policy` all **SUCCESS** on commit `d4152cdf9e970ce69c1f0be2b09886a20e25e4f9`. New V115 CI must be checked independently after publishing and must not be inferred from local QA.
