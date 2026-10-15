# ABC v11 first immutable Bybit historical-market diagnostic

**Status:** COMPLETE, research only, candidate **REJECTED FOR DEMO** on negative validation and unfavorable stress costs. All measurements as of 2026-10-15 UTC. These are historical observations, **not** prospective uninspected holdout results, revenue forecasts, live positions, or Paper account equity changes.

## Source, provenance and native execution

- GitHub source used **exactly**: `c96b2f2a8ba447c14acea1594f6db811163944e6`, draft PR #2662. The subsequent evidence-only commit(s) are not the evaluated source identity.
- Frozen native Windows research host: `DESKTOP-F4SA4VL` (LAPTOP2); Laptop1 Paper writer untouched; VPS work owner-paused.
- Hosted Test CI at source head: run `38683647217`: **Ubuntu, Windows, macOS all SUCCESS**; permission policy and research evidence refresh SUCCESS.
- Source and fixture hashes: **54 physical source files** passed immutable comparison. Bybit archive: **6 raw parquet file hashes** and archive/zip/manifest identity verified; previous v9 journal/ledger untouched.
- Native gate for the exact head: **61/61 PASS, 0 errors, 0 failures**.
- One parent-owned child process: PID `7132`, **exit code 0**, no timeout, approximately 76 seconds elapsed; no retry.
- Frozen invocation SHA-256 `fd72694d72bc67d46e9673b385e1c56d4090ff7a87c745ac3a9616a435849ffb`.
- Immutable market results SHA-256 `2aa967092412ea8edff27793cc190b4b036208ea1c3dc068d99b2a262a77a49d`; actual fill trace SHA-256 `dedf89ff796b958f1afe1e930414e3f7718ac77924831e2946020face295836d`.
- Raw Bybit dataset semantic SHA-256 `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`.
- On LAPTOP2 evidence preserved at `E:\NEXUS-QA\abc-v11-market-first-20261015\`: `invocation.json`, `producer.py`, `launcher.py`, `parent-exit-receipt.json`, `market-results.json`, `actual-fill-trace.json`, `independent-decimal-qa.json`, `independent-raw-chronology-qa.json`, process stdout/stderr, locks and source-bound preflight receipts.

## Twelve diagnostic cells

Currency **USDT**. Each cell starts a separate synthetic **10,000 USDT cash account**. Round trips, net realized profit/loss, and per-trade mean are based on actual observed trade trace; no minimum trade-count screen. Costs: conservative **10 bps fee + 5 bps slip per leg**; stress **25 bps fee + 15 bps slip per leg**. All partitions are chronological: train 60%; validation 20%; final previously-inspected history 20% (NOT pristine).

| Symbol | Partition | Closed trips | Conservative net | Stress net | First price-cross events |
|---|---|---:|---:|---:|---:|
| BTCUSDT | Train | 18 | +7.47658952 | −74.85484318 | 99 |
| BTCUSDT | Validation | 8 | −56.05103892 | −87.53565083 | 34 |
| BTCUSDT | Previously inspected test | 3 | −27.64282922 | −39.46481383 | 32 |
| ETHUSDT | Train | 18 | −75.67860586 | −192.43464422 | 92 |
| ETHUSDT | Validation | 16 | −41.93007477 | −104.27859254 | 36 |
| ETHUSDT | Previously inspected test | 6 | −24.91387975 | −57.84979348 | 32 |

The profile-specific trade counts and first price-cross events are equal for both profiles; only simulated fills, fees and resulting P/L differ in this run.

### Independent partition sums, not compound-account performance

| Symbol | Profile | Closed trips | Sum of isolated-partition net USDT | Mean closed trade USDT |
|---|---|---:|---:|---:|
| BTCUSDT | Conservative | 29 | −76.21727862 | −2.62818202 |
| BTCUSDT | Stress | 29 | −201.85530784 | −6.96052786 |
| ETHUSDT | Conservative | 40 | −142.52256038 | −3.56306401 |
| ETHUSDT | Stress | 40 | −354.56303024 | −8.86407576 |

**Validation gate fails on both pairs under both profiles.** Positive conservative BTC train P/L (+7.48 USDT) does not support promotion: validation loses −56.05, historical inspected last fold loses −27.64, and stress train alone loses −74.85.

## Independent checks

- Independent Decimal bookkeeper reconciled **all 12 cells, all 138 closed-trade records across both cost profiles** (69 fee-independent trades), entry/exit slippage, fees, each trade P/L, net returns and following-bar fills. PASSED.
- Separate independent raw OHLC auditor validated **325 unique first price-cross events / 650 profile-event records** and **138 exit records** using the immutable original 15m parquet prices, historical pivot index/confirmation latency, predeclared geometric ranges, first close crossing, cost-feasibility calculation, actual next-bar raw opening price and same-bar stop-first exit priority. PASSED. Audit output SHA-256 `2c07de7ee0ed1b38d6882aa4ab49ee63728d2b6c8e973674d813308db4eedb91`.
- From 650 repeated-profile event records, denial-field occurrences were: `h4_up` **356**, `abc_stress_cost_feasible` **262**, `h1_vol_ok` **94**. These are **overlapping** reasons, not independent additive drop counts. `h1_vol_ok` is a 1h **normalized candle-range / volatility** gate, not traded volume.
- The independent OHLC audit is not an independent line-by-line reconstruction of every higher-timeframe feature, nor a truly uninspected market holdout. Historical test history has already been inspected in earlier NEXUS research.
- Raw artifact files, full numerical calculations and source hashes remain on LAPTOP2. This GitHub summary reproduces the checked outputs and hash references; it is **not** a claim that all binary trace files were committed here.

## Decision and next work

**No automatic Strategy Finder registration or Demo promotion.** No Live trading, no change to the installed NEXUS app, no Paper writer change, no VPS work.

ABC four-pivot corrective reclaim increased opportunity count relative to the former Elliott five-swing shape (325 vs. 24 historical first price-cross events), but that frequency alone did not create an economic edge. In this preregistered configuration, the validation and stress tests fail decisively. Do **not** tune using the previously-inspected last fold, eliminate the cost screen, or misrepresent the results as a forecast. Further structural hypotheses require **separate preregistration and independent future prospective data**.

The monthly realized-trade aggregation is a **separate derived report**, not another backtest; do not claim it delivered until its file and reconciliation are independently verified.
