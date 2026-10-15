# Elliott V22 — official August 2026 monthly raw trade acquisition

**Date:** 2026-10-15. **Disposition:** `PASS_TWO_AUGUST_ARCHIVES_TRANSPORT_ONLY`. This proves direct raw-file acquisition and complete compressed-stream integrity, **not** individual trade correctness, continuous v2 candle history, recursive Elliott classification, future strategy returns, or eligibility for Demo.

## Exact native execution

From research Laptop2 `DESKTOP-F4SA4VL`, direct public requests to `https://public.bybit.com/spot` yielded HTTP 200 for four monthly archive HEAD checks (BTC and ETH, August and September 2026). Approximate compressed Content-Lengths were BTC Aug 109,705,306; ETH Aug 52,869,747; BTC Sep 128,140,828; ETH Sep 64,310,937 bytes. The September files were **not downloaded** in this bounded run.

Then [capture_august_monthly.py](capture_august_monthly.py) made **two** direct public archive GET calls with zero retries, zero redirects, no credentials, no Bybit private APIs and no orders; files were written **only** to a newly created local root:

`E:\NEXUS-QA\elliott-v22-august-official-20261015`

Each file was written to `.part`, streaming-SHA256-hashed, verified again from disk, gzip-decompressed through its CRC/footer in constant memory, checked against the complete `Content-Length`, and only then atomically renamed.

| Verified official Spot raw archive | Compressed size | gzip newline count | Raw SHA-256 |
|---|---:|---:|---|
| `BTCUSDT-2026-08.csv.gz` | 109,705,306 bytes | 15,618,766 | `08fe0babad662446591593c5b7b709460823b629567b7f6db28f7a2f3f295f3f` |
| `ETHUSDT-2026-08.csv.gz` | 52,869,747 bytes | 6,256,096 | `9a07649b8d5a67d8a3b786e032e933e8b3848f3c95af2be0800d7564aea7b14b` |

Uncompressed streamed bytes were 698,395,889 BTC and 271,420,194 ETH. The monthly first CSV row is `id,timestamp,price,volume,side`; this differs from the October 8 daily source's six-column `id,timestamp,price,volume,side,rpi`. Use the existing source parser's schema detection; **do not coerce both to an assumed identical column layout**.

The original complete [native receipt](NATIVE_AUGUST_MONTHLY_CAPTURE.json) also includes the direct source URLs, response metadata, byte hashes and timestamps. Four isolated safety tests in `tests/test_nexus_elliott_v22_august_transport.py` passed on Laptop2, covering zero order authority, refusal to modify an existing root, full gzip CRC and rejection of truncated gzips.

## Limitations and next bounded operation

1. The acquisition test verifies file transport, gzip integrity and apparent CSV layout. `trade_parser_audit_complete=false`: it does **not** certify all 21.9 million CSV lines as individually valid trades. No v2 Parquet candles were generated in this step.
2. Source access from Laptop2 to the official public raw archive is confirmed for the two August files. The September monthly archives, October 9–14 daily files and October 15 (not listed at initial check) require separate capture and validation. Existing October 8 raw gzips are already hash-registered in V21.
3. Preserve the old 2022–July archive, V19 July31–Aug1 pilot and V20 Sep8–Oct7 segment. The absence of a full uniform source-model v2 timeline **still blocks** the V15/V14 → V17 prospective Elliott exit study and every Demo/Live promotion.
4. The next objective is separately capturing two September monthly raw trade archives and validating their source-level integrity, then using the existing official source planner and a new clean root only after all required source periods are available.

**Safety:** Research-only, two public-source GETs, no strategy backtest, no exchange orders, no modification to Laptop1, 500-USDT reference Paper, existing research archives or paused VPS. Draft PR #2673 remains unmerged.
