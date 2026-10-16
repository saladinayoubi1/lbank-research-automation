# Elliott V74 — Full legacy composite-engine future-prefix invariance

**Date:** 2026-10-16 UTC. **Repo/branch:** Draft PR #2673, isolated Laptop2 research checkout. **Read-only:** no orders, fills, new P/L, Demo/Paper changes, Live, source retuning, or frozen V52 changes.

## Specific outstanding scientific question

V71 physically rechecked the original 10 historical Elliott legacy simulated trades' next-open entries and OHLC-backed stop/target exits. V72 demonstrated prefix causality of the original five-swing **feature helper** for those exact 10 decision moments, while V73 independently checked the four H1/H4 context fields' latest completed parent bar at each of the same decisions. Neither by itself evaluated every feature output of the original combined `nexus_composite_strategy_research.build_features` engine: changes in its other regime/context, volatility, macro, candle-volume or generation features could theoretically alter previously observable output when future market rows are appended.

V74 evaluates **all original composite feature DataFrame columns simultaneously**, without modifying the original algorithm or fitting parameters to historical losses.

## Physical and reproducibility anchors

- Source is the previously verified historical Bybit BTCUSDT and ETHUSDT archive through **2026-07-31**, loaded with the original immutable verified archive adapter, from each original 15m, 1h and 4h timeframe.
- Original legacy simulated trace SHA256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c` is rehashed and must reproduce precisely **10 distinct recorded trade decision times** across conservative/stress cost profiles. Duplicate profile decision times must agree.
- The original historical five-swing feature and composite-engine source files (original `PARAMETERS["feature_sha256"]` records) are reopened and SHA-matched. The existing `build_features` is imported and executed **unchanged** from the isolated original research adapter.
- For each entry decision UTC `T`, only physical 15m OHLCV with **OPEN + 15m ≤ T**, physical 1h OHLCV with **OPEN + 1h ≤ T**, and physical 4h OHLCV with **OPEN + 4h ≤ T** are admitted into the baseline.
- Each 15m baseline has **1,152 completed 15m source bars**; each H1 baseline has 421 eligible completed parent bars and each H4 baseline 161. All are drawn by source close-time, not array-index guesses. Validation rejects missing 15m/parent source-grid intervals, a partial parent candle, future-endpoint mismatch, and source tampering.
- Three input versions are evaluated by the **original unchanged engine**: baseline at `T`; then baseline plus **12 actual future 15m bars** and **8 future 1h and 8 future 4h bars**; then those same future-only bars with substantially altered highs, lows, closes and volumes (valid OHLC retained).
- The **entire original feature DataFrame before and at `T`** is compared column-for-column using exact equality including NaN/dtypes. Any different prior cell, output schema or chronology immediately raises `COMPOSITE_FUTURE_LEAK_*`.

## Actual historical outcome

| Physically sourced invariant | Verified result |
|---|---|
| Frozen, distinct original legacy simulated decision instants | **10/10** |
| Composite engine output columns compared, including all available legacy features | **83** |
| Baseline completed 15m bars per sample | **1,152** |
| Future actual 15m bars added | **12** |
| Future actual H1 and H4 bars added | **8 of each** |
| Previously observable feature DataFrame unchanged with future-source append | **10/10** |
| Previously observable feature DataFrame unchanged with extreme future-only OHLCV tampering | **10/10** |
| Original engine implementation modified | **No** |
| New actual Demo fill / positive P&L / V52 prospective score | **None** |

**Local physical source-backed evidence:** `E:\NEXUS-QA\elliott-v74-composite-prefix-20261016\V74_PHYSICAL_FULL_COMPOSITE_AUDIT.json`, SHA256 `dd16b9173176785e3eef42340fbc5fb2e0d37f5bb2e604e7365f968fcc5402e7`, verified process `EXIT_CODE=0`. The physical report discloses that not every historical market bar nor later V52 recursive 3m wave structure was tested.

## Adversarial tests and acceptance

Standalone source: `research/elliott_v74_full_composite_prefix/composite_prefix_v74.py`. Nine portable synthetic regressions `research/elliott_v74_full_composite_prefix/test_composite_prefix_v74.py` enrolled through `tests/test_nexus_elliott_v74_full_composite.py`; **9/9 focused tests passed on Laptop2 before GitHub publication**. Cases include a genuinely causal synthetic engine, deliberately future-dependent 15m closing price, deliberately future-only price-high leak, deliberately future-dependent 4h close, parent exact close boundary, missing 1h source interval, naïve timestamp, altered source digest, and nonexecution safeguards. Deliberate leakers are **rejected**, showing the check is not vacuously always passing.

**Important limitation:** Unchanged outputs on these ten already inspected decision instants are necessary but not sufficient to establish that the strategy generalizes, or that every engineering path is look-ahead free. It does **not** independently validate publication/receipt time of old market archives, original feature behavior at every one of 128,544 historical 15m bars, real bid/ask and orderbook or actual fills, the later source-bound V52 15m/3m Elliott classifier, or new profitability. The previously inspected legacy economics remain adverse: conservative total **-16.6141 USDT**, stress total **-56.4680 USDT** (V70). No old candidate is eligible for Demo promotion.

## Release safety and next gate

PR remains **Draft, not merged**. After committing V74, native full suite and hosted Windows/macOS/Ubuntu CI must be checked **at exact new HEAD** before claiming them fully green. V52 prospective experiment SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, warmup Oct16–17 UTC and scored Oct18–Nov16 UTC exclusive, remains unchanged. Real scoring requires physically published full-day Bybit archives and V69 source-observability checks before each archived result may be reported. Laptop1 installed app, Demo/Paper history, user profile, VPS and live-trading prohibition are unchanged.
