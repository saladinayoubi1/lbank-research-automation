# Elliott V79 — independently archived Bybit Spot trade-print order resolves a historical stop-bar ambiguity

**Research time:** 2026-10-16 UTC. **Scope:** pre-inspected **ETHUSDT September 11, 2025 12:15–12:30 UTC** validation transaction from frozen 10-trade **legacy** five-swing backtest. Isolated Laptop2; Draft PR #2673. **Not** live data at historical decision time, a new profitable wave, proof of an executable quote, a filled order, or a rescored V52 holdout.

## Question carried forward from V78

V77 verified against the original 15-minute OHLC that **20/20** stress/conservative historical simulated entry–exit paths triggered on their earliest eligible source bar, without an earlier source bar crossing a stop or target. V78 found that **one** ETH validation trade (trade index 2), recorded as a stop **inside its entry candle**, had its final OHLC HIGH above a hypothetical +1R threshold under both cost scenarios. A candle's HIGH and LOW carry **no intrabar event order**, making it methodologically wrong to claim a +1R gain before the recorded stop based on OHLC alone.

The historical entry was `2025-09-11T12:15:00Z`, source 15m bar index `97489`, original reference entry price **4453.52 USDT/ETH**, and both cost-profile simulated original exits were **stops** on the same 15-minute bar. Their original stop prices differ because the frozen cost/friction/risk model differs: conservative **4438.776402857143** and stress **4443.229922857144**.

## New independently downloaded physical source

On 2026-10-16, Laptop2 fetched the original Bybit public historical Spot gzipped day archive with a direct HTTPS, certificate-validated, no-redirect and no-proxy request:

`https://public.bybit.com/spot/ETHUSDT/ETHUSDT_2025-09-11.csv.gz`

- Direct response **HTTP 200**; archive size **5,440,636 compressed bytes**; HTTP Last-Modified `Fri, 12 Sep 2025 02:00:56 GMT`.
- Raw immutable local file `E:\NEXUS-QA\elliott-v79-raw-tick-order-20261016\ETHUSDT_2025-09-11.csv.gz`; SHA256 **`adaa67da56a9273de0343af880c06d15bc5db1988fc0bce0e2b3a1e8f89636fa`**. Source is HTTP-public and exchange-unsigned, **not** an independent cryptographically signed exchange feed.
- Source CSV fields: `id,timestamp,price,volume,side,rpi`, with millisecond integer timestamps. The script validates all rows, strict UTC day membership, nondecreasing chronological timestamps and decimal trade prices. **765,597** trade-print rows occurred across the day, of which **15,771** belong to the ambiguous 12:15–12:30 UTC bar.
- Trade-print OHLC independently reconstructed from just those 15,771 rows: **O=4453.52, H=4473.78, L=4437.63, C=4472.59 USDT**. **Every price equals the original separately verified legacy Bybit 15m candle exactly**, a four-way OHLC check with zero observed error, before considering intrabar ordering.
- The raw source-file receipt `E:\NEXUS-QA\elliott-v79-raw-tick-order-20261016\V79_RAW_HTTP_CAPTURE_RECEIPT.json` records URL, transfer size/hash, TLS retrieval time, Last-Modified, schema and sample rows; the actual gzip is deliberately **not** committed to GitHub.

The research script additionally rehashes the original legacy event trace SHA256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c` and V77 immutable physical first-touch report SHA256 `6e842b71af41f43a78c3e70c3e148ee1896153123aad8e4e2a8cc8f7660806e3`. A different raw source, legacy trace or first-touch receipt is rejected.

## Actual chronological first **trade-price prints**, NOT simulated executions

At each originally fixed stop and a hypothetical **+1R trade-price threshold** defined as `entry_reference + (entry_reference - original_stop)`, V79 finds the very first public trade print within the frozen 15m bar crossing each threshold. It compares millisecond timestamps, **never** using row order to invent priority between simultaneous-millisecond events.

| Original risk profile | First trade print at/below original stop | First print at/above hypothetical +1R | Chronological result |
|---|---|---|---|
| Conservative | **12:17:19.067 UTC**, print 4438.42 | **12:29:14.529 UTC**, print 4468.32 | **STOP PRINT FIRST** |
| Higher-cost stress | **12:16:25.380 UTC**, print 4443.15 | **12:26:55.276 UTC**, print 4463.82 | **STOP PRINT FIRST** |

Both profiles preserve original entry reference **4453.52 USDT**. The fixed hypothetical +1R trade-price lines are conservative **4468.263597142857** and stress **4463.810077142856**, respectively. The original simulation's actual profit targets were **4489.687474285714** and **4494.140994285715**, not +1R, and neither has been redefined. **This explicitly falsifies a historical interpretation that the +1R high happened before the stop in this original observed bar.** It does not imply a real trader could have entered or exited at precisely those print prices.

**Final immutable V79 physically source-verified receipt:** `E:\NEXUS-QA\elliott-v79-raw-tick-order-20261016\V79_FINAL_PHYSICAL_TRADEPRINT_ORDER.json`; SHA256 **`112afff246688fcfa942834f4eed202ba2a84ffac02a92a62015f8c7ecd5ad04`**; local direct physical replay `EXIT_CODE=0`. An earlier immutable scratch receipt with a less precise metadata field name remains archived, not substituted for the final receipt.

## Tests and hard limitations

- Portable read-only audit `research/elliott_v79_historical_spot_tradeprint_order/raw_tick_order_v79.py`.
- Independent test suite `research/elliott_v79_historical_spot_tradeprint_order/test_raw_tick_order_v79.py`, discovered via `tests/test_nexus_elliott_v79_tradeprint_order.py`.
- **10/10 focused native tests PASS** locally. They deliberately test stop-first, +1R-first, same-millisecond indeterminacy, missing thresholds, out-of-order timestamps, altered schema, malformed row volume/side/date, no market prints in window, malformed Decimal and research-only flags. Synthetic cases prove the comparator isn't rigged to always prefer a stop.
- Full native Elliott suite and Windows/macOS/Ubuntu CI at this new commit must be verified before claiming the release is globally green.

**Limits:** A public historical trade-print feed does not prove original 2025 intraday archive availability, executable contemporaneous bid/ask, queue priority, slippage, individual fill, or real P/L. The ability to reconstruct a retrospective sequence after 2025-09-12 cannot be used to backdate a 2025 trade. This is **not** an additional profitable candidate, not a counterfactual optimized stop, and not an Elliott signal that can be promoted into Demo. The already-inspected 10-trade legacy model still had conservative **−16.6141 USDT** and higher-cost stress **−56.4680 USDT** historical simulated net P/L, with negative validation **even before costs**. No alteration to original V37, V70–V78 evidence or strategy thresholds.

**Frozen unrelated V52 prospective protocol:** original Bybit Spot BTC/ETH 15m parent and 3m child, SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, warmup Oct16–17 2026 UTC, scored-source days Oct18–Nov15 UTC inclusive, Nov16 exclusive. The first scored daily archive cannot physically complete before **Oct19 00:00 UTC** plus actual publication delay; archive arrival must be evidence-bound through V58/V59/V60/V69. No Demo, VPS, Laptop1, or Live Trading changes. Draft PR remains unmerged.

**Scientific decision:** stop precedes +1R print for both historical cost profiles, so don't count that stopped trade as an assumed profitable exit. Proceed to genuinely unseen/source-timed future Elliott observations rather than retrospectively optimizing the losing legacy trades.
