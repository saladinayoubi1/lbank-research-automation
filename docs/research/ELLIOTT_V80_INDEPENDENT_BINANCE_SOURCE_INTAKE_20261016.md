# Elliott V80 — Independent Binance Source Intake (Research Only)

## Boundaries
- **Source:** official Binance Spot BTCUSDT and ETHUSDT, 1-minute daily archives for 2024-03-01 and 2024-03-02 UTC.
- **Purpose:** independent market-source intake, official checksum validation, 1m continuity and 3m/15m aggregation. *Not* a verified Elliott candidate, Elliott backtest, trading signal, filled order, P/L or prospective score.
- **Source timestamps:** 2024 archives use **milliseconds**, checked by exact 60,000 ms steps and 59,999 ms close time.
- **Integrity:** each ZIP SHA-256 matches its separately downloaded `.CHECKSUM` manifest; exact one-member ZIP CSV, 1,440 rows/day, contiguous across day boundaries.
- **Cross-exchange caveat:** Binance wick/volume/market microstructure must not be assumed equal to Bybit. These 2024 files are exploratory historical cross-venue evidence, not an untouched prospective holdout or training set.
- **Security:** no API credentials, no orders, no Demo, no Live Trading; laptop-1 install and the V52 protocol untouched.

## Independent observed receipt
The four ZIPs and their official CHECKSUM files, plus locally generated 3m/15m CSVs, are on laptop-2 under:
`E:\NEXUS-QA\elliott-v80-binance-source-20261016`

Hash-bound receipt committed separately:
`docs/evidence/elliott-v80-binance-source-20261016/V80_OFFICIAL_BINANCE_SOURCE_QA.json`.

The receipt records distinct acquisition start/end UTC timestamps, official checksum, local ZIP and CSV member SHA-256 for each file and aggregate CSV SHA-256. Raw ZIP files are intentionally not committed to Git.

## Results
- BTCUSDT: 2,880 1m; 960 3m; 192 15m complete candles.
- ETHUSDT: 2,880 1m; 960 3m; 192 15m complete candles.
- All 4 official ZIP checksums and timeline/OHLC structural checks passed.
- Source-audit execution returned `EXIT_CODE=0`, `V80_SOURCE_QA_PASS`.
- Dedicated tests exercise gap, time-unit, ZIP member and malformed OHLC rejection, and aggregation shape.

## Next scientific gate
On a separately declared exploratory historical window, apply **unchanged** Elliott structural/right-confirmation rules with explicit as-of timestamps; count candidates/rejections and compare venue-dependent source properties without parameter adjustment. Do not use historical exploratory observations to tune frozen V52. True forward evaluation starts on the pre-registered UTC dates and requires genuinely available, timestamp-attested Bybit files.
