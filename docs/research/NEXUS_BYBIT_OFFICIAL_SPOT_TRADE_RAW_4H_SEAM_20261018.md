# NEXUS — official Bybit Spot raw trade archive: authenticated-host research source seam pilot (18 Oct 2026)

## Substantive data-source discovery

**The direct V5 market API remained HTTP 403 on both authorized NEXUS Windows laptops, but the separate first-party public trade archive `https://public.bybit.com/spot/BTCUSDT/` and `https://public.bybit.com/spot/ETHUSDT/` returned HTTP 200 on Laptop2**. These are different public Bybit services. A failed V5 API request therefore does not establish that all official Bybit historical market data are unavailable. This is not a proxy, different exchange, residential-IP workaround, NEXUS Demo connection or authentication-key operation.

The official public Spot download directory contains per-day `BTCUSDT_YYYY-MM-DD.csv.gz` and `ETHUSDT_YYYY-MM-DD.csv.gz` files, including **August 1 and October 17, 2026**, which extend beyond the project's existing archive ending **July 31, 2026**. The raw daily CSV schema observed on both pairs was exactly:
`id,timestamp,price,volume,side,rpi`; timestamps are UTC Unix milliseconds, trade IDs increase, prices and quantities are physical base/quote trading values, and daily trade files are gzip-compressed.

**Six real official-host files were downloaded into an isolated QA tree on Laptop2**, each with unique SHA256 and reviewed exact-date/source filename. The total over these six **selected sample days** is **1,633,447 individual Spot trade rows**, NOT 1.6 million across the entire August–October interval. Files chosen deliberately for source seam and recent warmup only:

| Original official-host file | Actual raw trade rows | Compressed bytes | Full raw SHA256 first eight |
|---|---:|---:|---|
| BTCUSDT 2026-07-31 | 481,468 | 3,128,914 | `3d2a7d32` |
| BTCUSDT 2026-08-01 | 221,151 | 1,416,832 | `be6bf75c` |
| BTCUSDT 2026-10-17 | 468,696 | 2,793,440 | `63ec6056` |
| ETHUSDT 2026-07-31 | 160,308 | 1,426,166 | `1b81677c` |
| ETHUSDT 2026-08-01 | 89,507 | 767,275 | `c70b1666` |
| ETHUSDT 2026-10-17 | 212,317 | 1,567,092 | `4819e901` |

All full 64-character source digests and six complete 4h OHLCV rows per day are recorded in `research/bybit_official_spot_daily_raw_sample_claims_20261018.json` and `docs/evidence/bybit-official-spot-raw-4h-20261018/six-day-btc-eth-raw-trade-4h-sample.json`. The full downloaded gzip bytes reside **on isolated Laptop2 only**, not GitHub. HTTP status 200, official domain and matching raw bytes are good traceable provenance **but are not a cryptographic exchange signature or a complete independent provider certificate**.

## Critical old-to-new 4h source seam proof

The original Bybit BTC/ETH 4-hour canonical Parquet source previously pinned by the six-archive SHA mechanism ends with its 4h opening **2026-07-31 20:00 UTC**, and each has exactly **8,034** original 4h source rows. To prevent replacing true original historical bars with fabricated prices, a *separate first implementation* streamed the official raw trades from July 31, grouped by UTC 4h boundaries, and compared each reconstructed open/high/low/close/volume field against the original separately loaded canonical Parquet day.

- **BTCUSDT July 31:** 6/6 original 4h UTC candles exactly matched every OHLCV field: **zero price deltas and zero volume deltas**.
- **ETHUSDT July 31:** same **6/6 exact OHLCV matches**.
- **Total: 12/12** old-source identical physical OHLCV 4h candles on the overlap day, from **641,776 original raw trades** across the two assets. This is a meaningful real source-format/aggregation cross-check, not merely a schema check.
- The very next source day **August 1 2026** was reconstructed from physical trades for both symbols (6 4h bars each), and the newer **October 17 2026** was also reconstructed (6 each), proving that some authentic-host *pre-future-scoring warmup dates* are available. **The days August 2–October 16 have NOT been collected or proven continuous in this work.**
- All six selected daily datasets contain one or more trades in each UTC 4h bucket. The adapter rejects any missing bucket rather than forward-filling a candle. These older sample bars must **never count as a 90-day prospective evaluation**: the user's frozen score window begins only on **2026-10-19T00:00:00Z** and ends 2027-01-17 exclusive.

The historical source-seam comparison result and source-bar values are stored at `docs/evidence/bybit-official-spot-raw-4h-20261018/six-day-original-seam-crosscheck.json`. Its checked-in exact normalized LF SHA256 is `b3c3f16fb99e06486e89ac987f18190d2770eda3620b0190e3ada9403f9cf843`. The independent new fixed source adapter result's **canonical digest** is `d51f9062df36d590f2d60d7d1edb59107d2e4a58613a133c80db4cf6ee80559a`, based on the same six raw byte pins.

## Engineering change: offline, original 4h Spot source materialization

`scripts/nexus_bybit_official_spot_raw_4h_adapter.py` is an **opt-in offline** original raw Spot CSV.gz → genuine 4h UTC OHLCV adapter. It processes **one completed daily archive at a time** and retains only six running OHLCV buckets in memory, rather than loading a huge BTC/ETH multi-month trades DataFrame on the second laptop's ~4 GB RAM.

Input security and causal correctness checks:
- Byte SHA256 of complete original .csv.gz against separately recorded exact `research/bybit_official_spot_daily_raw_sample_claims_20261018.json` original raw receipts; correct exact symbol/ISO-day filename; rejects symlink, undersized/oversized/unavailable file. SHA validates source continuity of **bytes**, but the separate provenance of receipt/origin still demands human independent review.
- Parses the exact trade CSV header, verifies gzip decompression/checksum, strictly increasing trade IDs, nondecreasing physical UTC Unix-millisecond timestamps **within that calendar day**, positive finite price and base volume, permitted buy/sell directions, expected `rpi` values, physical first/open–last/close.
- No resampling of missing raw periods, no synthetic candle, no candle from a future interval, no UTC timezone guess or unequal BTC/ETH pairs. Exactly six nonempty 4h buckets per complete UTC day.
- Full result reports exact gzip SHA and raw row count, each true per-bucket OHLCV/trades/first-last tick timestamps, explicit source-type `SPOT_RAW_TRADE_NOT_SPOT_KLINE_API`, research-only authority `paper_eligible=false`, `live_enabled=false`, `orders=0`, and `not_future_prospective_holdout=true`.

The current CLI sample batch is restricted to **at most 12 files** (six frozen here). It is **not** a new automatic source downloader and **not** a complete daily Aug–October ingestion pipeline. Full future source materialization requires a separately reviewed sequential dated manifest and independent source verification. It also requires the existing archived six SHA source check to run again at the actual join point; the six-file raw trade sample only corroborates the **July 31 OHLCV seam**, not the immutable identity of a later combined whole dataset.

## Original frozen future validation contract is unchanged

PR #2724 is merged into GitHub main and freezes the original portfolio v3 `dual_rotation` candidate `b4e4a2c33304aec1`, optional default-off causal DD20 risk control, single 500-USDT BTC/ETH Spot wallet, fixed modeled conservative/stress/severe execution costs, and a **future** time horizon starting October 19.

Its previously written source preflight `scripts/nexus_portfolio_v3_forward_source_preflight.py` currently demands a receipt claiming the **V5 market Kline API**. Raw trade archives via `public.bybit.com/spot` are a **different official source representation and must NOT be silently relabeled as a successful V5 Kline API response**. Before they can become a scored original-source prospective future study, a **separate versioned research-source approval** must explicitly permit the trade archive and verify entire contiguous post-July datasets, old-archive seam, completed 90-day data, independent provenance QA and unchanged candidate/risk/fees. Nothing in this PR changes the prior preflight's source policy or promotes a strategy to Paper.

## QA and decision

On Laptop2 the strictly offline adapter ran the **six genuine official-host file samples and returned native exit 0**, canonical digest `d51f9062df36d590f2d60d7d1edb59107d2e4a58613a133c80db4cf6ee80559a`. The other independent simple trade-stream aggregator's July 31 canonical OHLCV parity independently passed for both old-source symbols. The new test suite `tests/test_nexus_bybit_official_spot_raw_4h_adapter.py` + `tests/test_nexus_bybit_official_spot_raw_source_evidence.py` completed **19 native passes, 1 skipped** (symlink creation requires Windows privilege in that environment), zero failing cases. Both pass/fail numeric, identity, temporal, missing-bucket and provenance-disclaimer regressions tested.

**Research source decision:** `OFFICIAL_SPOT_RAW_TRADES_ACCESSIBLE__SAMPLED_4H_SEAM_12_OF_12_MATCH__CONTIGUOUS_FUTURE_SOURCE_NOT_YET_APPROVED`.

This resolves the blanket conclusion that Bybit market data cannot be researched at all from the connected laptops, while remaining clear that the original 403 **V5 API** remains blocked. There is a plausible first-party source of newer original BTC/ETH Spot trades to fill the warmup gap **without changing exchange or circumventing restrictions**. The actual broader 2026 Aug–Oct complete capture, 2026-10-19→2027-01-17 prospective collection, review of raw Spot market cost/lot assumptions and independent future simulation are **not done here**. The owner Laptop1 install/Bybit Demo positions/profile/journal and global `Live=false` remain untouched.
