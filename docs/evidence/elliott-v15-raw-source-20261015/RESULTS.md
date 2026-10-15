# Elliott V15 — independent raw OHLC verification of frozen five-swing price events

**2026-10-15**. Native Laptop2, archive-source QA only. No new market discovery, strategy replay, backtest, live/demo action, or revised historical return calculation.

## Observed result

**PASS_FROZEN_PRICE_EVENT_PIVOT_SOURCE_QA**: **24/24 unique previously recorded first-break price events** match independent source reconstruction, **0 mismatches**. Eleven BTC and thirteen ETH historical events were checked. The old trace contains 48 event rows across the two cost profiles; exactly 24 duplicate-profile appearances were reconciled to the same unchanged setup fields before deduplication. See the actual native [machine receipt](FROZEN_EVENT_SOURCE_QA.json).

- Research host: `DESKTOP-F4SA4VL`, isolated result location `E:\NEXUS-QA\elliott-v15-raw-source-20261015\result.json`.
- Frozen archived trace: `E:\NEXUS-QA\elliott-five-swing-market-correction-20261015\actual-fill-trace.json`, byte SHA-256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`. This is the **old already-evaluated five-swing result**, not an unseen performance sample.
- Input: frozen Bybit `C:\NEXUS\research-cache\replay-canonical-37681826492\archive\bybit_market\{btc_usdt,eth_usdt}\minute15.parquet`; source SHA-256 enforced for BTC `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226` and ETH `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`.

## What the independent audit checks

1. Only a **complete contiguous timezone-aware UTC OPEN-timestamped prefix** of each 15m source archive through the already recorded event decision bar is allowed. A candle becomes available at OPEN+15m. No bars after the archived decision are passed to the checker.
2. Reconstruct each strict three-right-candle local high/low confirmation independently of the previous strategy feature producer. Exclude tied extrema and bars that appear to be both an extremal high and low (unknowable intrabar order). For consecutive same-type extrema, keep only the more extreme observed pivot, retaining the latest seven accepted pivots.
3. Compare immutable trace anchors exactly to independently reconstructed pivot data: origin index/low, fifth-high index/price, corrective-low index/price, and corrective-low confirmation index. Check the original bounded seven-pivot geometry, all parent path constraints, confirmation lag, age limit and structural nonoverlap against raw source prices.
4. Report **observed provenance** only; `entry_signal=false`, `paper_eligible=false`, `recursive_elliott_proven=false`. Matching a real source-bound seven-pivot structure does **not** certify recursive Elliott degree, full 5-3-5-3-5 subdivision, a correct trading entry, or positive expected P/L.

The 17 new source-verification synthetic tests ran successfully (17/17) on Laptop2, including adversarial incorrect/tampered pivot price, backdated confirmation, source gaps, future-tail insertion, invalid OHLC, tied/outside pivots, overlap and unconfirmed setup cases.

## Economic and scientific disposition

**The remaining Elliott failure is NOT demonstrated to be pivot extraction corruption in these 24 events.** The earlier five-swing candidate remains **unprofitable or unqualified on inspected historical validation**; 24 recorded first-break events and 10 admitted entries are far too few to establish robust expectancy. Proving a profitable alternative requires a separate, preregistered strategy with correctly sourced **fully recursive** structure where supported, independent next-OPEN executed fill and structural-stop order-path QA, realistic friction, MAE/MFE, and truly future **uninspected** Bybit data. Do not select thresholds from the already-seen folds.

Related evidence: [full-archive 1h/4h as-of QA](../elliott-v14-asof-qa-20261015/FULL_ARCHIVE_ASOF_RESULTS.md). Source-only checker: [V15](../../../../nexus_elliott_source_bound_v15.py) and [frozen-event validator](frozen_event_source_qa.py).

**Authority and deployment:** Research only, branch stacked as Draft PR #2673 over Draft #2661, GitHub is truth. Existing on-disk Laptop1 app, sole Paper writer, reference 500 USDT, Bybit-only demo, archived ledger, prior economic loss evidence and paused VPS unchanged. `Live=false`.
