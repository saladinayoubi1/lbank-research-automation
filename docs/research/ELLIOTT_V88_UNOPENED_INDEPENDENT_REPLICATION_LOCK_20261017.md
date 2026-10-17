# NEXUS Elliott V88 — preregistered independent historical replication LOCK (2026-10-17)

**Status: LOCKED SOURCE SELECTION ONLY.** No July 2024 archives were downloaded, parsed, visualized or scored by this task. This note and `V88_PREREGISTRATION.json` must be committed and independently identified by GitHub commit SHA **before** any V89 ingestion. V88 source eligibility is NOT an Elliott trading signal, an out-of-sample profitability conclusion, or proof of forward performance.

## Fixed, outcome-blind evaluation calendar
- **Exchange/data:** official Binance Spot `data.binance.vision/data/spot/daily/klines`, daily **1m**, `BTCUSDT` and `ETHUSDT`. Research data only; **Bybit remains the sole possible DEMO/PAPER execution venue**, inactive in this task.
- **UTC calendar:** **2024-07-01 00:00** (inclusive) to **2024-07-15 00:00** (exclusive): **14 whole UTC days per pair**, **20,160 base candles per pair**, aggregate **6,720 3m** and **1,344 15m** bars per pair if complete.
- **Replications:** A = July 1–7 UTC; B = July 8–14 UTC. Both are held aside for fixed-rule evaluation; **NO calibration or new threshold selection** on A before inspecting B. All 28 ZIPs plus corresponding official `.CHECKSUM` files must be present and valid. **No substituted days, no exchange interpolation/filling gaps**.
- **Selection rule:** the first two complete Monday-to-Sunday weeks in July 2024 were calendar-selected independently from the previously inspected March 1–2 2024 development examples. This is a **newly specified historical replication**, not a prospective forward test. We have not established that no other researcher ever examined these dates; only that **V88 itself does not open them**.

## Fixed recognition and rejection gates
The full immutable JSON describes all candidate families and refusal reasons. The evaluation stage must reuse the unchanged V82–V87 **research-only** observers:
1. V82: full source-bound strict **15m width-3 parent**, **3m width-1 child**, each uniquely mapped to strict **1m width-3 physical** center, right-confirmed at the actual bar close. All primitive centers remain; no wave-count re-selection or pruning.
2. V83: a conventional ordinary Impulse *necessary geometry* test, including wave 3 not shortest and wave 4 non-overlap. A geometry pass still does **not** prove a complete Elliott motive wave.
3. V85: separate diagonal veto; ordinary impulse wave-4 non-overlap does **not** transfer to diagonal; still reject wave 3 shortest. Diagonal position/wedge and internal subwave anatomy remain **unproven** unless independently authenticated.
4. V86: strict **1m width-1** internal degree, explicit intra-OHLC dual-extremum abstention; no conveniently compressed pivots.
5. V87: examine Zigzag **5-3-5** and Flat **3-3-5** concurrently using their predeclared internal *primitive count skeletons* **4/2/4** and **2/2/4** respectively, not isolated retracement ratios or profitability-led labels.

**All output is structural, not economic.** Records must include both valid and rejected candidate counts, reasons, all first-confirmed timestamps, input hashes, censored left boundary and counts by *first observable time* in A and B. No synthetic earlier history may be added at the July-1 left edge; all incomplete boundary observations fail closed. A candidate crossing week A/B belongs to the split in which its full candidate is first observable, not the split of its retroactively marked pivot center.

## Integrity and protocol controls
- `research/elliott_v88_replication_lock/lock_v88.py` is **manifest-only**: no downloader, no file market reader, no forward-result scorer. It emits all 28 exact official ZIP URLs and their `.CHECKSUM` links, source QA rules and fixed calendar. Unknown future ZIP hashes are `null` and `downloaded=false`, not invented or assumed verified.
- Frozen artifact: `docs/evidence/elliott-v88-frozen-independent-replication-20261017/V88_PREREGISTRATION.json`. SHA-256 **`fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899`**.
- Source ingestion in a **future, separately verified action after GitHub lock**: each archive must pass HTTP status, official CHECKSUM match, exact member CSV, 12-column source format, 1,440 aligned gapless one-minute OHLC rows, finite positive Decimal prices and exact close time; reject any missing/corrupt date and do not claim partial 14-day replication.
- V52 prospective scorer (Oct 18–Nov 15 2026 UTC) is **not read**. PR #2673 remains Draft; no merge and no Laptop1 Demo, journal, production runner, VPS or live exchange changes. No new trades, P/L or confirmation of an Elliott trading edge.

## Evidence gate before V89
Dedicated synthetic preregistration tests check determinism, exact source names, the 14-day two-split set, time and bar counts, unchanged family rules, false Live/Paper flags, refusal to overwrite the manifest and refusal to claim market files already downloaded. **Actual laptop2 verification:** dedicated V88 tests **16/16 PASS**, full Elliott suite **650/650 PASS**, `Ran 650 tests in 48.809s`, `OK`, native `V88_FULL_EXIT=0`. The complete test-output log is stored only on laptop2 at `E:\\NEXUS-QA\\elliott-v88-replication-lock-20261017\\V88_FULL_REGRESSION.txt`, SHA-256 `016d1f603af3ee0d9c3081a596f767a2689098572833c552d410aef47e0ecd8d`. No market data were fetched by V88.

**V89 next single objective:** collect the *already frozen* 28 authentic July 2024 daily files on Laptop2 with checksum, source integrity and immutable provenance receipts. Only after all verified should a later stage apply the frozen observers, reporting the full counts, ambiguity and zeros. Do not optimize parameters using either week. This is still historical retrospective evaluation, not forward evidence or Demo promotion.
