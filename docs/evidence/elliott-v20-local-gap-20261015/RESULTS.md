# NEXUS Elliott V20 — completed 30-day offline V2 archive and independent reconciliation

**Execution:** 2026-10-15 on research Laptop2 `DESKTOP-F4SA4VL`. **Final disposition: `PASS_ISOLATED_V20_30DAY_MODEL_V2_ONLY`.** The data are historically inspected and discontinuous with V19; **NOT eligible for V17 prospective economic evaluation, Strategy Finder promotion, Demo, or Live**.

## Exact work completed

- Independently reconstructed local cached BTCUSDT and ETHUSDT public-spot-trade gzips for **2026-09-08 through 2026-10-07 inclusive**, without using public/private exchange APIs. The official `bybit_spot_backfill.run_backfill` v2 source-row-order semantics processed **60 original local raw gzips** into a **new, isolated** `E:\NEXUS-QA\elliott-v20-30day-v2-20261015` root.
- Official `_backfill_report.json`: **30/30 date units complete**, **60/60 archives committed**, **0 failures**, **0 remaining**, `backfill_complete=true` and `current_dataset_integrity_ok=true`. The process was **not restarted or replayed** after the earlier remote-session delivery error; its original checkpoint and results were inspected in place.
- The new v2 `_candle_model.json` and `_source_manifest.json` are verified; each existing local gzip was independently rehashed against the manifest, and its fixed-date/pair slot validated.
- Produced and hash-bound all six complete UTC timeframes:

| Source | 15m per pair | 1h per pair | 4h per pair |
|---|---:|---:|---:|
| BTCUSDT | 2,880 | 720 | 180 |
| ETHUSDT | 2,880 | 720 | 180 |

- All **six parquet SHA-256s of the original two-day V19 pilot** were compared with its previously registered receipt, **unchanged**. The frozen older historical exchange archive and trading/paper journal were not operated on.

## V18 time-resolution fault detected and fixed

The first independent verification attempt exposed a code defect: the V18 15m-grid validator called `Series.astype("int64")` on parquet `datetime64[ms, UTC]` timestamps and incorrectly interpreted the resulting **millisecond ticks as nanoseconds**. The source chronology itself was contiguous; the validator's unit assumption was wrong. V18 now explicitly converts to `datetime64[ns, UTC]` before testing nanosecond modulo/step. A new adversarial test covers parquet `ms`, `us`, and `ns` datetimes plus misaligned timestamps: **24/24 V18 bridge tests PASS**. No market record was shifted, filled, reinterpreted as another candle, or rewritten.

The independent read-only [completed-state verifier](verify_completed_30day_v2.py) then succeeded and issued the original full `V20_OFFLINE_SEGMENT_RECEIPT.json` on Laptop2. This avoids a redundant 30-day backfill execution.

## Independent aggregation and QA

Using *only* the completed 15m parquets, [the separate aggregation auditor](audit_completed_30day_v2.py) recomputed OHLCV into 1h and 4h. Every UTC bucket boundary matched: **9,000 field comparisons across two symbols and two higher timeframes; 0 material mismatches** using fixed numerical representation tolerances. The [machine-readable GitHub receipt](NATIVE_30DAY_V2_INDEPENDENT_QA.json) contains each of the 60 local raw gzip SHA-256 identities, six resulting parquet hashes, six preserved V19 hashes, the checksum of the original full Laptop2 native V20 receipt, and all independent per-field comparison counts.

Native laptop validation on the evidence branch after fixing the time-unit defect:
- **183/183 Elliott source and research unit regressions PASS**.
- **12/12 official Bybit backfill and version-semantics migration `pytest` regressions PASS**.
- The CI status of the *latest documentation commit* is checked separately in GitHub; local QA must not be misrepresented as hosted multi-platform success.

## Remaining blocked dependencies

The earlier V20 cached-source scan of `C:\NEXUS\research-cache` and `E:\NEXUS-QA` found only 60 day-pair source candidates in the **Sep 8–Oct 7** segment. **90 pair/day slots are missing**, comprising:

| Missing date range (inclusive, UTC) | Days | BTC/ETH raw-file slots |
|---|---:|---:|
| 2026-08-02 through 2026-09-07 | 37 | 74 |
| 2026-10-08 through 2026-10-15 | 8 | 16 |
| **Total** | **45** | **90** |

The existing separate V19 July31/Aug1 pilot and V20 Sep8/Oct7 segment must not be concatenated over those gaps. Do not substitute the old mixed/unversioned archive or the earlier unauthenticated public REST-Kline transcription. The local gzip files have content hashes and valid trade-derived aggregation but their original provider origin has **not been newly independently attested**. Public API retries had returned HTTP 403 previously; no network calls or restriction workarounds were performed here.

The preregistered V17 window begins **2026-10-16 UTC**, and V17 is a bounded seven-pivot hypothetical exit model, **not recursive Elliott wave counting**. No genuinely unseen forward market observations, executed fills, realized or hypothetical prospective net returns, or positive expectancy have been demonstrated.

**Architecture/safety:** research only, Bybit only; GitHub Draft PR #2673; 500-USDT reference Paper remains unchanged on Laptop1, Live=false, automatic Demo=false, historical journals kept intact, VPS paused. Do not merge or promote until complete evidence and independent trading-strategy gates are satisfied.
