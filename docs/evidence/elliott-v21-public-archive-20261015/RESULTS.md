# NEXUS Elliott V21 — official Bybit raw trade archive availability and 8 October source capture

**Date:** 2026-10-15. **Disposition: PASS_TWO_OFFICIAL_DAILY_RAW_SOURCE_FILES_ONLY.** Research-only, no backtest/strategy inference/trading signal and no exchange credentials.

## Public archive inventory independently checked

The repo's actual source base is `https://public.bybit.com/spot`, established in `bybit_spot_archive_audit.py`. The official BTC and ETH directory listings were checked directly:

- https://public.bybit.com/spot/BTCUSDT/
- https://public.bybit.com/spot/ETHUSDT/

**Verified filename presence for both pairs:**
- Full-month trade archives `BTCUSDT-2026-08.csv.gz`, `ETHUSDT-2026-08.csv.gz`, `BTCUSDT-2026-09.csv.gz`, and `ETHUSDT-2026-09.csv.gz`. These were **listed**, not downloaded in this bounded task.
- Both daily source files for every day **2026-10-08 through 2026-10-14**, totaling **14 daily files**. Oct 15 is **not listed at time of verification**, and 2026-10-15 UTC trading day is not yet complete. There are therefore **18 listed additional official raw files of the 20 identified in the optimized inventory plan**. A listing is not a checked file hash and does not prove full content validity or permitted network access from every location.

The existing `bybit_spot_backfill.build_archive_plan` uses monthly trade archives **only when a full calendar month is covered for both pairs**; otherwise it selects eligible daily files. Source identity and model-v2 version must remain uniform. Do not concatenate old legacy/historical Parquet, a REST Kline, and row-stable raw-trade candles.

## Narrow actual capture on research Laptop2

Verified laptop2 `DESKTOP-F4SA4VL` direct HEAD over HTTPS `public.bybit.com` returned HTTP 200. Then ran the [strict bounded raw capture script](capture_oct08_raw.py) in the existing isolated Draft branch, with a fresh output root:

`E:\NEXUS-QA\elliott-v21-public-spot-20261015`

Only **two** original gzip trade files, for 2026-10-08, were fetched with one direct GET each; no retries, no redirects, no private endpoint, no credentials. Byte SHA-256, URL, HTTP response status, archive `Content-Length`, reported `Last-Modified`, gzip CRC/integrity, CSV row count, trade parser schema and all source row validity counters were captured in the [exact native evidence](NATIVE_OFFICIAL_OCT08_CAPTURE_RECEIPT.json).

| Source | Response | Raw gzip bytes | Valid trade rows | SHA-256 |
|---|---:|---:|---:|---|
| BTCUSDT Oct 8 | HTTP 200 | 10,914,045 | 1,808,386 | `5c59096544af3ac73e9b13c06bd6209bc12c56fc204350b51bfa92d0e0000219` |
| ETHUSDT Oct 8 | HTTP 200 | 3,689,239 | 517,584 | `247090d2327736987bb1651859e5cc3769ec1e596320850c002ec78f2bd7d89d` |

Each parse reports 0 invalid numeric/side/symbol/price/size/out-of-range trades, 0 duplicated trade IDs and 0 skipped/malformed CSV rows. The original raw source files remain available on Laptop2 in the isolated capture root.

Three synthetic safety tests for source lock-down, refusal to overwrite existing output, and **single-shot fail-closed HTTP 403 with no retry/redirect** passed natively, **3/3**.

## Scientific and operational gate

This capture *reduces source availability uncertainty*, not the preregistered financial decision risk. V19 July 31–Aug 1, V20 Sep 8–Oct 7, and new official Oct 8 source remain **disconnected** historical datasets. For a fully versioned, correctly ordered BTC/ETH v2 trade archive, still acquire and verify remaining listed August/September monthly archives plus Oct 9–14 daily, and check Oct 15 source once the UTC day is complete and published. Rebuild **one fresh** end-to-end continuous v2 dataset via the source planner, not by splicing stale Parquet. Confirm first/last closed bars and full 15m/1h/4h provenance and statistical holdout eligibility.

No historical trading returns or Elliott source filters were recomputed, no V17 prospective P/L was evaluated, no Strategy Finder or Demo/Paper promotion, no Live, no VPS actions, and no files in V19/V20/installed Laptop1 were overwritten. Draft PR #2673 and Issue #2672 remain review authorities.
