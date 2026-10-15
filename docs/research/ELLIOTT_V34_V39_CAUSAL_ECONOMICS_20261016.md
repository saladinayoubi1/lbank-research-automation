# Elliott V34–V39 — source-bound causal research and loss attribution

**Date:** 2026-10-16  
**Scope:** Research/Backtest/Paper-Demo boundaries only. This evidence does **not** enable Demo, orders, or Live trading.  
**Runner:** Laptop2 `DESKTOP-F4SA4VL`; Laptop1 Paper writer and paused VPS untouched.  
**Status:** Diagnosed, **NOT** a proven profitable or complete recursive Elliott strategy. PR #2673 remains Draft.

## 1. Data provenance and independent cross-check

The 2026-10-01..2026-10-14 inclusive Bybit public Spot BTCUSDT/ETHUSDT daily raw trade archives were downloaded into distinct append-free evidence directories and SHA-256 bound to official URLs, HTTP 200 and compressed byte lengths. All 28 inputs passed the source-row parser, UTC-day, gzip CRC and within-file trade-ID checks. V33 rebuilt a brand-new independent `nexus.bybit-source-row-stable-candles.v2` archive; no older V19/V20 dataset was concatenated.

**V34 independent stream oracle:** 16,214,613 raw trades; 3,528 reconstructed 15m/H1/H4 candles; 17,640 OHLCV numeric comparisons; **zero** timestamp/value mismatches. Both 15m series contain 1,344 bars, H1 336, H4 84, for the 14-day interval.

**V38 independent overlap:** Separately, 2026-10-01..07 was compared between protected V20 (Sep08–Oct07, also V2 semantics) and fresh V33 (Oct01–14). 1,764 matched candle timestamps and **8,820** OHLCV comparisons passed with zero mismatches. This comparison **did not** splice datasets or reclassify previously inspected history as an unseen holdout.

## 2. Untuned structural Elliott diagnostic

The existing causal **7-pivot five-swing** algorithm is not a true recursive 5-3-5-3-5 plus ABC counter. Its old geometric/risk rules were **not** changed.

| Verified isolated period | Symbol | Latest 7-pivot cases | Geometry passes | Path-valid setups | Fresh closed fifth-high breakouts |
|---|---|---:|---:|---:|---:|
| V33 Oct01–14 | BTCUSDT | 113 | 0 | 0 | **0** |
| V33 Oct01–14 | ETHUSDT | 112 | 2 | 1 | **0** |
| V20 Sep08–Oct07 | BTCUSDT | 256 | 1 | 1 | **0** |
| V20 Sep08–Oct07 | ETHUSDT | 262 | 2 | 2 | **0** |

V36 event trace: an ETH setup formed at **2026-10-02 06:30 UTC** and survived four 15m decision bars. Its frozen breakout threshold was **2748.42**; highest eligible closed price was **2731.61** (0.612% below), then a new accepted pivot replaced the prior structure. No qualifying breakout, executed fill, or observed P/L occurred.

**V39 independent geometry rejection attribution:** Across the 518 latest 7-pivot cases in V20, the first failing rule was bullish origin/wave2/wave3 ordering for **323**, and wave4 non-overlap/fifth-high ordering for **175**. Only **3** passed all geometry rules. V33 has 225 corresponding cases, only 2 geometry passes. These are diagnostics: changing the thresholds based on this inspected sample would be retrospective overfitting, not an established improvement.

## 3. Frozen historical trade economics (not from V33/V20)

The separate **previously inspected** 10-trade backtest trace and result file matched their frozen SHA-256 receipts and independent decimal economics QA:

| Historical simulation, 10,000 USDT reference | Conservative | Stress |
|---|---:|---:|
| Closed trades | 10 | 10 |
| Targets / Stops | 4 / 6 | 4 / 6 |
| Net P/L, USDT | **−16.6141** | **−56.4680** |
| Modeled reference-price-to-net friction, USDT | 29.9789 | 79.7554 |

With the **conservative** profile the train partition had +7.9633 USDT / 5 trades, validation −17.6745 USDT / 4 trades, previously inspected test −6.9029 USDT / 1 trade. The historical result is **not** the user's 500-USDT Paper balance and does not establish positive edge. Fee and slippage assumptions contribute materially to the negative result, alongside stop-hit frequency.

## 4. Immutable local receipts (SHA-256)

All files below reside on **Laptop2**. This GitHub document records their provenance and findings; it does not claim those local JSON files have been uploaded to GitHub.

| Local relative research path / receipt | SHA-256 |
|---|---|
| `elliott-v33-oct01-14-v2-20261016/INDEPENDENT_FULL_CANDLE_QA.json` | `dfcdfe8dac5189a7ca41a3521ba7183f02fad2dd9b62e9ff01dc35dd9931a0e9` |
| `elliott-v33-oct01-14-v2-20261016/HISTORICAL_ELLIOTT_DIAGNOSTIC.json` | `a7f7690f0b0db7b228fd71e3b167b8ff1fa4196b29400455b42271f9984d21b2` |
| `elliott-v36-causal-funnel-20261016/CAUSAL_FUNNEL_RECEIPT.json` | `70de733f1252e123ebe8d1564061715c909b765d05119c0322049c3aee2ad320` |
| `elliott-v37-frozen-loss-attribution-20261016/LOSS_ATTRIBUTION.json` | `96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024` |
| `elliott-v38-crosssource-30day-20261016/SOURCE_OVERLAP_QA.json` | `120de75de110f33fd63ccfd5b05d59e9dcdcec5850032532ca1ffefa36edf1de` |
| `elliott-v38-crosssource-30day-20261016/V20_30DAY_ELLIOTT_FUNNEL.json` | `3874f8c74914b2f28a338ac6c3f4f587c25de6f7bf65d8a191267cd4073607f3` |
| `elliott-v39-geometry-forensics-20261016/GEOMETRY_REJECTION_AUDIT.json` | `e10da2ff7b9a052c84019dd5dbf59e7e0c18aff3598c8e2eecf0ee8edbf6387f` |

Root prefix: `E:\NEXUS-QA\`.

## 5. Next gated research action

1. Introduce an isolated, **causal multi-degree subwave-and-ABC research classifier** that explicitly verifies 5-3-5-3-5 subdivisions and the chosen ABC correction type against immutable lower-timeframe raw evidence; tests must reject ambiguous/incomplete/future pivots. This is **not** achieved by the existing 7-pivot review.
2. Keep fixed timing and entry/exit semantics: completed decision candle, post-signal best bid/ask (V26), valid spread/quote age, independently observed Fill, conservative stop-first/gap logic, fees/slippage.
3. Assess economic validity only on genuinely unseen, prospectively preregistered source with count, gross/net, MAE/MFE and uncertainty; no historical winner-based parameter retuning. Require independent QA and a **separate** Demo admission gate. **Live remains prohibited.**

**Admission now:** `entry_signal=false`, `paper_eligible=false`, `auto_demo=false`, `live_enabled=false`, `observed_pnl=null`.
