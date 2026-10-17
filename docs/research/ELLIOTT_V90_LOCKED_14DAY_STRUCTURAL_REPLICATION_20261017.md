# NEXUS V90 — locked July 14-day Elliott structural replication

**Status:** completed historical source-bound structural census; NOT a trade backtest or proof of profit. Bybit Demo/Paper only; Live disabled. V52, Laptop1 install and VPS untouched. PR #2673 stays Draft.

## Precommitted source sequence

V88 locked both July evaluation weeks **before accessing the sample**: commit `6c6e57fefe96246f6fedaa12223d5ed544eb88dc`, SHA-256 `fae91774a57f887fc14122b4b1c74a26f6c7ad5daac28488c4e440b836523899`. V89 later acquired the **28 original Binance Spot daily 1m ZIP plus official CHECKSUM files** (2024-07-01 to 2024-07-14 UTC for BTCUSDT and ETHUSDT), validated 1,440 OHLC candles per archive, and committed source receipt `7f61fa134ecd1e937f3aa9a242820f5f3e99d322`; SHA-256 `e1c3988f6112ccd12883e35704b63024dc56bf52cc7a38f36ef42e743c2ed7df`.

V90 reopens every original ZIP/CHECKSUM locally, revalidates every minute and checks source hashes against the immutable **Git-committed** V89 receipt before applying **unchanged V82–V87 functions**. No adaptive pivot pruning or ratio tuning, no score calibration on either July week. Every parent interval and both motive/correction hypotheses preserve their original right-confirmation timestamps and source reasons.

## Historical sample result

| Source-backed metric | BTC | ETH | Total |
|---|---:|---:|---:|
| Complete physical 1m rows | 20,160 | 20,160 | 40,320 |
| V82 15m parent witnesses | 243 | 249 | 492 |
| V82 3m child witnesses | 2,291 | 2,387 | 4,678 |
| Consecutive parent intervals | 242 | 248 | **490** |
| Provisional five-leg motive skeletons | 6 | 2 | **8** |
| Provisional three-leg correction skeletons | 9 | 14 | **23** |
| Ordinary impulse *necessary geometry only* pass | 1 | 0 | **1** |
| Diagonal *necessary geometry only* preliminary | 2 | 0 | **2** |
| Proven recursive Elliott patterns, signals or trades | **0** | **0** | **0** |

**Crucial:** A necessary-geometry pass is **NOT** a complete Elliott pattern. The one BTC ordinary-impulse case and two BTC preliminary diagonal cases are incomplete; no Zigzag 5-3-5 or Flat 3-3-5 source-bound complete subwave hierarchy is proven. None implies an entry, fill, P/L or profit.

## Classification by first observable confirmation time

| Event class | Week A: Jul 1–7 | Week B: Jul 8–14 | Total |
|---|---:|---:|---:|
| BTC parent intervals | 118 | 124 | 242 |
| ETH parent intervals | 123 | 125 | 248 |
| BTC five-leg skeletons | 0 | 6 | 6 |
| ETH five-leg skeletons | 0 | 2 | 2 |
| BTC three-leg skeletons | 4 | 5 | 9 |
| ETH three-leg skeletons | 9 | 5 | 14 |
| Complete Elliott trading certificates | 0 | 0 | 0 |

Causal split: first observable **right-confirmed closed-minute UTC instant**, never retroactive pivot-center UTC. Week B includes the Jul 14 final candle first observable at **Jul 15 00:00 UTC**. The Jul 1 left boundary is **censored**, not padded with invented earlier warmup history. Both weeks are evaluation-only; no tuning on week A before week B.

## Source and pattern rejection accountability

The complete evidence JSON includes every one of the 490 parent intervals: timestamped parent centers, right-confirmations, all visible child pivots, original V82 rejection reason, first observable split, and nested state. Every five-leg case includes V83 ordinary-impulse hard rules, V85 diagonal necessary veto and V86 1m anatomy; every three-leg case includes V87 Zigzag/Flat competing hypotheses, all internal points and any ambiguous dual-extrema candle. Same-kind and inconvenient pivots are **never silently removed**.

Key aggregate: **7/8** five-leg skeletons fail conventional impulse hard geometry (BTC 5, ETH 2). The 8 diagonal checks produce **6 hard vetoes**, only 2 preliminary geometry cases, no verified internal five-leg diagonal. All **23** three-leg correction skeletons remain unconfirmed; none becomes a fully proven Zigzag/Flat.

The April-to-July selection history does not establish a prospective holdout or an out-of-sample economic edge. July is a precommitted historical structural replication, **not** the V52 future score window (Oct 18–Nov 15 2026 UTC). There is no defined costed entry/exit and therefore no trade count, net P/L, expectancy or fill realism to report. A passing test suite is only software QA.

## Evidence and safety

Detailed evidence: `docs/evidence/elliott-v90-independent-replication-20261017/V90_REPLICATION_AUDIT.json`. All physical ZIP source data and full local logs remain on Laptop2, not in Git. No trading system change, no paper journal change, no production runner intervention. PR #2673 must stay Draft/open/unmerged.

Next independently pre-register an uninspected source period and **complete** wave-degree/subwave and pattern-position grammar before further analysis. Only after a genuinely executable rule passes out-of-sample cost-inclusive Bybit Demo/Paper QA can it be considered for Demo promotion. Live Trading never enabled.

## Verification record

- **Dedicated V90 contract tests: 10/10 PASS**, native `EXIT_CODE=0`, SHA-256 local log `985e23b700dd824ff84b6d0b80c29cd86ffef94f0706f1cbc0ed9d08f05f953e`.
- **Full Elliott regression: 679/679 PASS**, `Ran 679 tests in 49.312s`, `OK`, native `V90_FULL_EXIT=0`, SHA-256 local log `5b7252b90b12a6c58f6e159abc5eeb9e3002a1f23e1c2d7e2980e36fe4ac62d1`.
- The independently hashed detailed V90 JSON evidence SHA-256: `1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a`; identical evidence is retained both in Git and in the Laptop2 local research directory.
- Source archive receipt and frozen pre-registration were SHA-verified before the full July evaluation. The Python suite passing does not constitute investment or trading performance evidence.
