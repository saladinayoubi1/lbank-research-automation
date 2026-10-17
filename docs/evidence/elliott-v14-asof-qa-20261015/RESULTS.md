# Elliott v14 — independent Bybit higher-timeframe source and as-of feature QA

**Disposition: PASS_NARROW_SOURCE_VALUE_QA, 0 mismatches.** Executed on Laptop2 `DESKTOP-F4SA4VL`, 2026-10-15 UTC. This is a read-only diagnostic of an **already inspected historical dataset**. No signal, strategy market evaluation, backtest, paper order, live action or retrospective optimization was executed. Preserve all prior Elliott v9, five-swing and ABC v11 economic findings.

## Source and scope

- Frozen Bybit archive: `C:\NEXUS\research-cache\replay-canonical-37681826492\archive`.
- Six `minute15/hour1/hour4.parquet` inputs for BTCUSDT and ETHUSDT matched the exact historical file SHA-256 bindings in the earlier five-swing first-market invocation; receipts in [INDEPENDENT_ASOF_QA.json](./INDEPENDENT_ASOF_QA.json).
- The on-device research engine `nexus_composite_strategy_research.py` was separately SHA-256-checked as `9931aaeb51a25fb0fbeb5f3b5384ddc8d15eff5b3ccbfc10dd7161ca4b40d2b7`, matching the source-frozen five-swing invocation.
- For each symbol: 128,544 complete 15m OHLCV, 32,136 1h and 8,034 4h records. 15m source candles were independently grouped by actual UTC OPEN time into 1h and 4h bars. All 5 OHLCV fields matched the stored 1h and 4h series within explicit numerical tolerances. Price-field maximum difference **zero**; volume-only floating-roundoff at most `7.28e-12`.
- Derived parent higher-timeframe filters independently from those reconstructed candles: 1h normalized range `h1_vol_ok` and closed 4h `h4_up`. Independently resolved the latest fully closed source bar for each 15m decision via binary search on higher-timeframe close timestamps.
- Compared against the unchanged original `build_features` only (NOT `signal_for`/`backtest`). Per symbol, first and last 8,192 15m bars from the frozen archive; excluded first seven days of each slice as rolling-warmup. **7,520 decision bars per window** for each of 2 symbols, 2 windows and 2 feature flags = **60,160 exact binary-value comparisons**, **0 mismatches**.

## Integrity and what is NOT established

| Gate | Result |
|---|---|
| Frozen raw parquet hashes | PASS, 6/6 |
| Complete UTC OHLCV grid, aggregate consistency | PASS for 15m→1h/4h, both pairs |
| 1h/4h feature close availability and exact as-of values | PASS, 60,160/60,160 |
| Source hash of reused computation engine | PASS |
| New Elliott market evaluation or fresh unseen holdout | **NOT RUN / NOT CLAIMED** |
| Full seven-pivot path provenance for every prospective signal | OPEN |
| Recursive Elliott degree and subwaves | OPEN |
| Actual structural-stop fill economics, net future expectancy, independent next-open trade QA | OPEN |
| Demo/Paper qualification | **BLOCKED** |

The two sampled feature windows are not a claim of an exhaustive decision-level audit of all 128,544 bars. The complete source OHLCV aggregates were compared; numerical feature equality was sampled at both archive edges. The independently reconstructed features follow the original declared formulas, not a second proof that those formulas predict gains.

## Reproducibility

- [QA source](./independent_higher_timeframe_qa.py) uses pinned Python/Pandas/NumPy, reads the six frozen source parquets and outputs a machine-readable receipt. It imports `nexus_composite_strategy_research` **only to call the read-only feature builder**, never a producer, trading signal or simulator.
- `INDEPENDENT_ASOF_QA.json` is the actual native receipt from Laptop2. Original result preserved at `E:\NEXUS-QA\elliott-v14-asof-qa-20261015\result.json`.
- One initial attempt failed due missing module search path when calling a nested script; no market test ran. The corrected environment `PYTHONPATH` invocation exited successfully with `PASS_NARROW_SOURCE_VALUE_QA`. No numeric parameters or data were changed.

**Boundary:** Laptop2 research only; GitHub source of truth, original old strategy files immutable; Laptop1 sole Paper writer unchanged, `Live=false`, automatic Demo promotion blocked, VPS owner-paused. PR #2673 remains Draft.
