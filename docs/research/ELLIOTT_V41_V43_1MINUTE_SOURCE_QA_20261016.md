# Elliott V41–V43 — Official Spot 1m Source Bridge and As-Of Gate

**Date:** 2026-10-16  
**Research device:** Laptop2 `DESKTOP-F4SA4VL`  
**GitHub PR:** #2673 (Draft, not merged).  
**Boundary:** research-only, no entry signals, no Paper promotion, Live disabled, VPS paused. All observed market data below are **historical and already inspected**, not a pristine prospective holdout.

## V41 — Real 1-minute candles, bounded to Oct 13–14, 2026

An offline, isolated source-row-stable converter independently SHA-256 checked the four raw official Bybit Spot BTC/ETH daily trade archives already admitted to the V33 source manifest, then generated minute-OPEN-labelled, complete UTC candles with ordering `raw timestamp millisecond, then original raw CSV row position`. It kept the old V33 and all source archives immutable.

| Pair | Verified original trade rows | Complete 1m bars | 15m/H1/H4 OHLCV checks against independently verified V33 | Failures |
|---|---:|---:|---:|---:|
| BTCUSDT | 2,382,211 | 2,880 | 1,260 | 0 |
| ETHUSDT | 650,646 | 2,880 | 1,260 | 0 |
| **Total** | **3,032,857** | **5,760** | **2,520** | **0** |

Outputs reside under `E:\NEXUS-QA\elliott-v41b-source1m-oct13-14-20261016`; source manifest is `PROVENANCE_RECEIPT.json`.

An initial V41 attempt correctly refused the comparison because the old V2 reference Parquet index was stored at millisecond timestamp resolution while the independently regrouped candles were nanosecond-resolved. The **timestamp values and intervals actually matched**. The corrected, separate V41b run normalized both timestamp indexes to nanoseconds before comparing. The original blocked receipt remains in `elliott-v41-source1m-oct13-14-20261016` and was not overwritten or concealed.

## V42 — Causal 1m as-of source gate, code in this Draft PR

`research/elliott_v42_source_asof/source_asof_v42.py` requires an externally supplied, valid SHA-256 that pins a physical Parquet file (the local V41b receipt supplies one). It rejects absent or hash-changed files, naive/off-grid/duplicated/missing UTC minutes, malformed OHLCV/trade counts, impossible decisions, and partial/future candles. It returns a complete **index-zero** prefix of already-closed 1-minute candles, excluding the persisted future tail.

- **16/16 isolated deterministic tests PASS**, including V40 integration proving a missing parent/child witness cannot produce a wave proof or trading authorization.
- **8/8 real-source as-of snapshots PASS** (four decision times for each of BTC/ETH, including a mid-archive timestamp and the archive close).
- Every real V40 call with no valid parent and child subwave evidence returned `PARENT_OR_ABC_OR_LEGS_MISSING`. This is correct **fail-closed** behavior, **not** evidence of no Elliott structure in the market.
- Updated `tests/test_nexus_elliott_v42_source_asof.py` registers V42 in native CI discovery. **293/293** Elliott-focused tests passed on Laptop2 checkout HEAD `78dfa262294bd69c991a19046dd3811e33bc5989` (before this documentation-only commit).

## V43 — Independent raw-trade-to-minute oracle

A separate second implementation re-read and re-hashed all four original compressed raw trade files, checked their physical timestamp ordering, and rebuilt each minute by streaming first/last/high/low and Decimal trade-volume accumulation. It did **not** call the V41 construction code or rewrite its saved candles.

- **3,032,857** source trades independently traversed.
- **5,760** physical one-minute OHLCV bars exactly matched the V41b time grid.
- **28,800** independent numeric OHLCV comparisons — **0 discrepancies**.
- **5,760** extra per-bar trade-count comparisons — **0 discrepancies**.

This independent result closes the bounded one-minute **source accuracy and chronology** gap for the selected two days only.

## Preserved local machine receipts (not uploaded as JSON)

| Receipt, relative to `E:\NEXUS-QA\` | SHA-256 |
|---|---|
| `elliott-v41b-source1m-oct13-14-20261016/PROVENANCE_RECEIPT.json` | `7430ce0c7e1bd6b8f969e530ea71b3ebe03ab2b8e8f9a9e537b4fd369ae002b1` |
| `elliott-v42-source-asof-20261016/REAL_ASOF_INTEGRATION_RECEIPT.json` | `1b7e579f0967d2fdd03aadcc8554bbeb29956598d736e720785bbec453473e7e` |
| `elliott-v43-independent1m-qa-20261016/INDEPENDENT_ONE_MINUTE_QA.json` | `686925eecd6f7c12fa77ecfabc803f28189762c9512f1267cb493764e04ec135` |

## Next substantive gate

The existing V40 `5-3-5-3-5 + ABC` validator is a **bounded one-child-degree witness checker**, not an autonomous hierarchical Elliott wave counter. Next, build a **causal multi-timeframe candidate proposer** on independently verified 1m and 15m sources that derives 15m parent anchors, reconciles each to confirmed 1m price extrema and children, excludes pivots not yet observable at the decision time, and tests the complete geometry on a *fixed, preregistered* protocol. Keep all unidentified/ambiguous counts rejected rather than inventing witnesses.

Only after independently confirmed source-bound wave candidates exist should post-signal quote, fill, stop/target/gap, fee/slippage, MFE/MAE and unseen prospective P/L be evaluated. Historical V41–V43 correctness **does not demonstrate profitable trades**.

**Invariant admission state:** `live=false`, `entry_signal=false`, `paper_eligible=false`, `auto_demo=false`, `new_pnl=null`.
