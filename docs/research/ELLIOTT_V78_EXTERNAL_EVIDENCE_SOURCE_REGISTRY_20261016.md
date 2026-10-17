# NEXUS Elliott — V78 independent external evidence registry (2026-10-16)

**Purpose:** Correct research-source narrowness. Until now most debugging and simulation evidence has come from one Bybit historical dataset and internally developed Elliott definitions. This is adequate for detecting implementation defects but is insufficient to establish a broadly applicable Elliott wave classifier. This document catalogs **externally verified reference sources** and their limits. **No external historical dataset has yet been downloaded, source-hashed and reproduced on Laptop2 merely by adding this document.** No new strategy performance claim follows.

## A. Rulebook / taxonomy references, not performance proof

1. **Elliott Wave International — Waveopedia, motive waves:** https://www.elliottwave.com/waveopedia/motive-waves/ . Five-wave motive structures and differentiation of impulse vs diagonal; wave 2 not more than 100% retracement, wave 3 not shortest.
2. **EWI — corrective waves:** https://www.elliottwave.com/waveopedia/corrective-waves/ . Explicit alternative families: **zigzag 5-3-5, flat 3-3-5, triangle 3-3-3-3-3** and combinations. A failed zigzag geometry DOES NOT license relabeling it as a successful flat/triangle without its own preregistered internal-count witness.
3. **EWI — alternation:** https://www.elliottwave.com/waveopedia/alternation/ . Differences between waves 2 and 4 are **guidelines**, not absolute diagnostic overrides.
4. **EWI — zigzag and historical labeled case examples:** https://www.elliottwave.com/waveopedia/zigzags/ . Example **DJIA July–Oct 1975 double zigzag**, **S&P 500 Jan 1977–Mar 1978 double zigzag**, published retrospectively; educational structures, **not** contemporaneous precommitted trading performance.
5. **EWI — flats (including running):** https://www.elliottwave.com/waveopedia/flats/ . Running flat rare, strict inner subdivisions mandatory; cannot be used to rescue the already inspected V63 failed ETH wave without independent gates.

**Research action, not existing validation:** separately encode objective grammar labels impulse, diagonal, zigzag, flat, triangle and combinations with frozen falsification examples and strict right-confirmed as-of timestamps. Keep this *new exploratory hypothesis* separate from original V52 frozen 15m/3m score, no cherry-picking a mode based on inspected ETH leg. Distinguish "allowed wave structure" from "timely entry with positive net expectancy."

## B. Independent exchange-authored price/history (DATA only)

**Highest-priority cross-venue comparison:**

- **Binance official public market archive** https://github.com/binance/binance-public-data and https://data.binance.vision/ . Daily/monthly **spot** trades and 1m/3m/5m/15m/1h/4h klines; companion `.CHECKSUM` files; spot timestamps are **microseconds from 2025-01-01** (previously milliseconds). This unit distinction MUST be normalized before BTC/ETH alignment. Public next-day availability is **not same-day execution observability**. Explicitly record the actual receipt UTC and check each archive checksum.
- **Coinbase Exchange official historical candles** https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-candles . Historical OHLCV via REST, at most **300 candles per request**, may omit intervals without trades; market is commonly **BTC-USD / ETH-USD**, not USDT pairs. USD vs USDT and venue liquidity/candle extremes can differ. Paginate and refuse to invent absent bars.
- **OKX official public historical candles** https://www.okx.com/docs-v5/en/ . `GET /api/v5/market/history-candles`, supports 1m/3m/5m/15m/1H/4H, up to 300 candles per request; includes candle `confirm` field, and higher timeframe timezone variant differences. Use only **SPOT BTC-USDT/ETH-USDT**, never accidentally replace with PERPETUAL/SWAP prices; explicitly check `confirm=1`.

**Data comparability gate:** track pair, quote currency, spot-vs-perp, exchange, interval, UTC open+close convention, unit conversion, trade corrections, gaps, file hash, physical receipt timestamp, and divergence. **Independent venues are not expected to have identical wick highs/lows or wave counts.** Separate the claim "exists on several venues with predeclared tolerances" from the stricter "same physical 1m pivots on Bybit." Cross-venue research must NEVER silently replace Bybit as the Demo exchange: **Bybit remains the only execution venue**, Research/Paper only; LBank/Bitget prior backup use is research, not migration.

## C. Other analysts' actual published Elliott case histories: hypotheses, NOT a ground-truth label oracle

- TradingView **Skyrexio**, article published April 28, 2024: https://www.tradingview.com/chart/BTCUSDT/HQzmAk4k-The-ultimate-guide-on-Elliott-waves-in-crypto-trading/ . Discusses **BTC Dec 2022–Apr 2023** Elliott wave labeling. This is **post-hoc explanation of an earlier chart**, not evidence its author predicted 2023 waves in 2022.
- TradingView **WaveTattva**, July 28, 2024: https://www.tradingview.com/chart/BTCUSD/6bpZ1ZbK-Elliott-Wave-Demonstration/ . Retrospective BTC wave anatomy, Fibonacci ratios and alternating-wave examples. Price-structure examples; no independently verified filled trades or P/L.
- Elliott Wave International Bitcoin example dated **December 11, 2024**: https://www.elliottwave.com/articles/a-bitcoin-chart-you-need-to-see-to-believe/ . Selected historical marketing chart; **survivorship/selection bias risk**, cannot infer all-call predictive performance.

**Strict annotation intake:** store immutable original publication timestamp, chart/underlying history range, each claimed label and invalidation level, whether the idea was published **before or after** the move, all available failed forecasts (not only winners), and whether original analysis was edited. Only timestamped forecasts made **before** the target event, with explicit exits and complete record of failures, can contribute to a fair forecast benchmark; retrospective examples are educational labels only.

## D. Academic/methodological guardrails

- Sullivan–Timmermann–White, *Data-Snooping, Technical Trading Rule Performance, and the Bootstrap* (1999): https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf — benchmark for multiple-testing/data-snooping concerns; NOT a demonstration that Elliott itself works.
- Academic discussion of Elliott + pattern recognition: https://www.sciencedirect.com/science/article/abs/pii/S0957417415002110 ; https://www.mdpi.com/2076-3417/14/24/11897 — research leads only; exact data, code, forward validation and economic results must be inspected before transferring any claim.

## E. Next atomic NEXUS research work

1. Choose one **pre-specified old historical BTC/ETH date window** distinct from V52 scored Oct18–Nov16, obtain Binance spot **1m BTCUSDT and ETHUSDT raw or kline source** in a new *isolated* Laptop2 research directory. Record URL, SHA/CHECKSUM, available timestamp and exact 1m continuity. **Do not** use the future untouched V52 holdout to design the model.
2. Run **exact existing** strict Bybit Elliott pivot/wave rules on Binance historical 1m, compare aggregate candidate counts, causal right-hand availability and source differences with Bybit **without changing any rule**. Distinguish generalization failure from physical candle mismatch.
3. Independently classify two historical annotated public Elliott case studies using date-stamped hindsight vs real-time labeling criteria; quantify agreement/disagreement, do not report public analysts' charts as audited profit.
4. Produce an evidence table before designing any new grammar (source, dates, hash, valid/invalid structure, as-of availability, cost-inclusive prospective admissibility). No Demo promotion without *new* verified prospective positive net outcome.

**Safety and project continuity:** Original V52 protocol immutable SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`; Oct16–17 UTC warmup, first scored source-day Oct18 UTC, full daily archive may not be available before Oct19 00:00 UTC plus exchange publication delay. This registry has **not modified V52, any scanner, Laptop1, journal, VPS, or trading endpoint**. Live trading disabled; Draft PR #2673 must not be merged without permission.
