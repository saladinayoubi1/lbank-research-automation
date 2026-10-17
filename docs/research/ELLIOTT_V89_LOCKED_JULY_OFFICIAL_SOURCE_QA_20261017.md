# NEXUS V89 — Locked historical July 2024 source acquisition and integrity audit

## Goal and frozen sequence
Source-only ingestion against the **already pushed and committed V88 preregistration**:
- V88 preregistration Git commit: `6c6e57fefe96246f6fedaa12223d5ed544eb88dc`
- V88 byte-precise SHA256: `fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899`
- 28 **preselected** daily Binance Spot 1m archives plus official matching `.zip.CHECKSUM` files, 2024-07-01 to 2024-07-14 UTC inclusive, **BTCUSDT and ETHUSDT**. No dates or instruments substituted. Source-data ingestion began **after** the preregistration commit; no July source file was inspected by V88.
- No strategy execution, V52 forward-score access, Demo, Bybit order, or Live trading.

## Actual acquisition
The V89 intake process on Laptop2 completed with native `EXIT_CODE=0`. Each official daily ZIP and its sidecar checksum passed HTTP response, exact filename, official SHA256, expected single CSV member, 12-column source schema, exactly 1440 1m candles, correct open/close Unix-millisecond UTC boundaries, contiguous zero-gap dates, strictly finite positive Decimal OHLC bounds and non-negative base volume.

| Verified physical source | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Daily source ZIP files with sidecar checksum | 14 | 14 |
| Complete physically valid 1m rows | **20,160** | **20,160** |
| 3m bars logically aggregatable (not yet separately scored) | 6,720 | 6,720 |
| 15m bars logically aggregatable (not yet separately scored) | 1,344 | 1,344 |
| Week A verified days (July 1–7) | 7 | 7 |
| Week B verified days (July 8–14) | 7 | 7 |
| Missing, rejected, altered or substituted days | **0** | **0** |

**Full 28-source receipt:** `docs/evidence/elliott-v89-official-source-20261017/V89_SOURCE_INTAKE.json`. Source receipt SHA256 `e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df`. The receipt records each exact official URL, official checksum, actual ZIP SHA256, member CSV SHA256, real UTC source boundaries, minimal source bounds and verification status. ZIP bytes and sidecar manifests are retained only in `E:\NEXUS-QA\elliott-v89-binance-source-20261017` on Laptop2; not in Git.

## Contract and failure isolation
`research/elliott_v89_source_intake/intake_v89.py` validates original V88 bytes and **the real committed historical Git object** before reading the July source. The downloader cannot substitute days and caches only a source that already passed official receipt and physical OHLC checks. Same-name cached bytes cannot be overwritten with changed data. Any corrupt/partial source results in a separate explicit `INCOMPLETE_NO_STRATEGY_EVALUATION` local receipt and no successful full-source certification.

The complete source-integrity receipt is intentionally **distinct** from frozen model hypotheses, performance evaluation, trading eligibility and all old V80/V82/V87 evidence. All pattern definitions continue unchanged. Future-tail invariance, point-in-time pivot observation, and candidate rejection are separate strategy gates for a later stage; they have **not** been applied to the newly downloaded July dates here.

## Tests and safety
- Dedicated source QA tests: **19/19 PASS** in `tests/test_nexus_elliott_v89_source_intake.py`. Coverage: byte-for-byte V88 Git lock, deterministic strict decimal and OHLC, full daily rows and timestamps, corrupted official checksums or ZIP members, extra member, gaps, NaN, bad volume, altered same-name cache, incomplete cached sidecars, exactly preapproved filenames.
- **Full Elliott-focused regression verified on Laptop2: 669/669 PASS**, `Ran 669 tests in 49.032s`, `OK`, native `V89_FULL_EXIT=0`. Off-repository full test log: `E:\\NEXUS-QA\\elliott-v89-binance-source-20261017\\V89_FULL_REGRESSION.txt`, SHA-256 `d446c32f0e2de0520939c81d3e87b5d2fc432e9181128cdb27d8b42d02df1894`.
- **Independent offline source replay:** All 28 physically cached archives and corresponding original `.CHECKSUM` sidecars revalidated without network; 28/28 PASS, native `OFFLINE_EXIT=0`, V89 receipt SHA unchanged `e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df`.
- Research-only: `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`, `new_pnl=null`. No new positions, no proven positive returns. **Not** the prospective V52 Oct 18–Nov 15 2026 score and not yet a strategy replication result.
- PR #2673 remains **Draft, unmerged**, Laptop1 Demo untouched, Windows runner untouched, VPS work paused.

## V90 next bounded gate
Only after verified V89 Git/source evidence: apply **frozen, unchanged V82–V87 structural observers** to *all* 14 days per symbol. Count all ordinary/motive/correction/abstain events by their first **right-confirmed observable** timestamp in locked weeks A and B; do not optimize based on either week. Full recursive Elliott, P/L, and Demo eligibility must remain unproven until separately demonstrated with a true out-of-sample cost-inclusive execution protocol.
