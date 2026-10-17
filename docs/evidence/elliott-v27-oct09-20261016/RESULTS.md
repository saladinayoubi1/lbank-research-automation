# NEXUS Elliott V27 — Oct 9 source integrity finalized without duplicate download

**2026-10-16.** Research-only, BTCUSDT and ETHUSDT Bybit public Spot source. **Native outcome: `PASS_OCT09_TWO_PAIRS_FULL_TRADE_AND_V2_GRID_QA`.** This is not a backtest result, actual execution or a forward-trading profit.

## What was found and verified

Before initiating a new source download, a separate research capture root was discovered already present on Laptop2:

`E:\NEXUS-QA\elliott-v27-oct09-official-20261016`

It contains **both** official public Spot `2026-10-09` raw gzip files, source-response headers and original capture receipts. A fresh-root capture script correctly **refused** to replace these files. **No duplicate download, splice, prior-archive rewrite or retry** was performed.

The initial v1 capture incorrectly marked all BTC lines invalid because the raw source stores lowercase `buy/sell`. The original v1 failure receipt remains unchanged. Its separate final v2 receipt correctly recognized the official lowercase sides and showed both files with valid gzip/size/hashes, but disclosed that duplicate ID checks were not yet complete.

To close precisely that gap, [verify_existing_oct09.py](verify_existing_oct09.py) ran **read-only**, using the existing `bybit_spot_archive_audit.read_trade_archive` and `bybit_spot_backfill.validate_trade_range` to normalize real raw-side case and verify all original row timestamps, prices, sizes, symbol, side and duplicate trade IDs, as well as any malformed/skipped source lines. The source file SHA-256s and pinned sizes were checked against the original receipt before analysis.

| Official Bybit source | Raw gzip bytes | Trade rows accepted | Duplicate trade IDs | SHA-256 |
|---|---:|---:|---:|---|
| `BTCUSDT_2026-10-09.csv.gz` | 5,989,359 | 1,012,531 | **0** | `d43ab98cc7d1b089af6a8aeeda623d2a41bfc8326f129e9424a15c99c1d346d6` |
| `ETHUSDT_2026-10-09.csv.gz` | 1,954,760 | 278,788 | **0** | `81225224c0570744212c281f6d35f4013f26791aa0602dee480c4f1438dac3bb` |

All trade-quality failure counters were zero. The repo's **source-row-order-stable v2** aggregator separately produced, *in memory and without writing parquets*, **96 complete 15-minute candles, 24 H1 candles and 6 H4 candles for each pair** over the single 2026-10-09 UTC day.

The exact machine-recorded independent result, including original receipt digest, decoder metadata, per-field zero-error counters and UTC candle boundaries, was committed at [NATIVE_OCT09_INDEPENDENT_QA.json](NATIVE_OCT09_INDEPENDENT_QA.json). The V27 offline native receipt is stored separately on Laptop2:

`E:\NEXUS-QA\elliott-v27-oct09-independent-20261016\QA_RECEIPT.json`

This does **not** imply these candles were inserted into the historical source. The v19/v20 independent datasets and the older 2022–July replay remain untouched.

## Acquisition/source status

On Laptop2, a *separate metadata-only* HEAD check of BTC Oct 9 returned HTTP 200 and BTC Oct 15 returned HTTP 404 **at this time**. Oct 15 ETH was not checked in this bounded step. Do not generalize this BTC result to other dates or permanent availability.

Official August and September 2026 monthly BTC/ETH gzip archives have their original SHA/transport receipts in V22/V23; Oct 8 pair in V21 and Oct 9 pair in V27 are preserved. **Oct 10–14 both pairs and Oct 15 subject to official release still need acquisition/verification** before an end-to-end uniform v2 contiguous rebuild.

## Strategy boundaries

Elliott V14–V26 causality and entry/exit controls remain distinct from profitability evidence. The limited seven-pivot filter is **not** a certified recursive 5-3-5-3-5 impulse/ABC wave count. V17 next-open hypothetical P/L is not an exchange fill; V24–V26 reject invalid breakout retests, same-bar stop/target ambiguity, late quotes, bad spreads and unobserved execution.

**No fresh Elliot signal or profit result was produced.** GitHub PR #2673 remains Draft; no paper-demo promotion, no Bybit order, no Live, no VPS and no Laptop1 journal/application changes. The 500 USDT Paper reference is unaffected.
