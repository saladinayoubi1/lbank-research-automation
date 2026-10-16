# NEXUS Elliott V99 — causally confirmed multiscale close-only swings (RESEARCH ONLY)

**Purpose:** address V91–V98's finding that every strict width-1 minute pivot cannot necessarily be treated as an Elliott subwave of a chosen degree. V99 is a *predeclared experimental multiscale directional-change heuristic*, **not** a proven wave-degree algorithm, a complete Elliott impulse/correction classifier, a Bybit Demo strategy, a backtest with profit, or a valid sample for parameter selection.

## Frozen inputs and no lookahead

- Read-only source: all **28 daily Binance Spot 1m ZIPs** for BTCUSDT and ETHUSDT, July 1–14 2024 UTC, originally source-locked V88, verified with official ZIP CHECKSUM and SHA receipts V89.
- Verify immutable V98 Git source from commit `545e705a710fad5ec185c334a66216bdbf5c76f8` and JSON SHA256 `dd6dd322ac84c80559dadc54f439ded417f1befd24b0c611310a06e4b080f490` via exact Git object bytes and ancestor. Verify 28 historical archives again; for every CSV candle, check `close` is within previously verified V90 source `low..high` and source first-open / closing timestamp.
- Run `research/elliott_v99_causal_scale/scale_v99.py` with separate immutable **CloseMinute(ms, Decimal close)** inputs; high-low intrabar ordering is never guessed, and no future OHLC data is supplied to the pivot algorithm.
- **Prior-closed adaptive threshold, frozen hypothetical settings**: trailing **60** absolute one-minute close changes, median multiplied independently by **3** (finer scale) and **8** (coarser scale), floored at **0.03% of previous closed price**. These are stated arbitrary engineering research hypotheses, not optimized on July or established Elliott theory.
- Streaming state starts after a 60-close-return warmup. Following a confirmed prior movement, track the best *observed CLOSE extreme*; emit a candidate turning point **only** when a later fully closed minute moves in the other direction by at least the pre-decision threshold. Record both historical center time and later confirmation time. Unconfirmed newest extremes are **never** output. All confirmed pivots remain in the original stream; no retrospective selection or pivot relabeling.
- The two scales are **independent**, not forcibly nested. Fewer coarse swings do not imply the coarse swings are certified higher-degree Elliott waves, nor that they must coincide with the fine extrema. No strategy performance or trades were computed.

## Diagnostic replay on already-inspected July 2024 (not prospective evaluation)

| Metric | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Independently source-verified historical close candles | 20,160 | 20,160 |
| Confirmed scale-3 close swings | **2,212** | **2,206** |
| Confirmed scale-8 close swings | **609** | **613** |
| Scale-3 week A / B confirmations | 1,099 / 1,113 | 1,088 / 1,118 |
| Scale-8 week A / B confirmations | 275 / 334 | 309 / 304 |
| Minimum center-to-confirmation lag | 2 minutes | 2 minutes |
| Certified Elliott degree assignments/patterns | **0** | **0** |
| Bybit Demo or Live orders, profit evaluation | **0 / none** | **0 / none** |

All statistics are about **close-confirmed directional changes only**, not observed five-wave counts, profitability or signals. The original 8 motive and 23 correction historical specimens were not retuned or rescored using these two scales. V99 verifies that recomputing through the end of Week B preserves all event objects already confirmed by the end of Week A (without revising past timestamps/centers). Canonical SHA256 digests of each complete event list and each source close stream are included in the evidence.

### QA and limitations

- Dedicated synthetic-only tests cover exact right-confirmation, prefix/future-tail invariance, strict no-lookahead threshold, timestamp gaps, incomplete warmup, NaN/negative/boolean prices, unknown scales, no last-bar unconfirmed extreme, alternating swing labels, and explicit research-only gates. No source ZIPs required to run unit tests in GitHub CI.
- Research report: `docs/evidence/elliott-v99-causal-scale-20261017/V99_CAUSAL_MULTISCALE_CLOSE_DIAGNOSTIC.json`. Original generated report is kept in the device's OS temporary folder; JSON output uses `-text` Git attributes to retain identical checksum bytes.
- Important risk: a close-only pivot can differ from wick-based extrema used by prior V82–V98. This is **not** validation or a replacement of earlier Elliott models: it merely offers an independently time-causal scale hypothesis. Median and multipliers are frozen until a future genuinely uninspected dataset is opened. This historical already-seen July universe **must not be used to tune** thresholds, select a profitable degree, or justify Demo promotion.

## Forward research gate, not deployment

Before even discussing trade entry/exit or P/L, implement a testable *independent mapping* from confirmed scale swings to source-attested, wave-positioned Elliott Impulse/Diagonal/Zigzag/Flat patterns. Require a separate future-data/forward-out-of-sample validation, classification precision / abstention analysis, right-confirmation latency, Bybit Demo spread/fees/slippage, stop-before-target conservative fills and disallow ambiguous positions. The frozen V52 Oct 18–Nov 15 2026 protocol and Laptop1 Demo stay unchanged. Bybit-only possible Demo/Paper exchange, Live never enabled, PR #2673 Draft and unmerged.

## Completed local test and evidence gates

- Synthetic-only tests of physical close source shape, strict previous-bar volatility window, confirmation timestamp, unknown-scale rejection, closed-prefix invariance, last-bar abstention and safety no-order contract: **17/17 PASS**, native exit `V99_UNIT_EXIT=0`.
- Full Elliott-focused Laptop2 suite: **827/827 PASS**, `Ran 827 tests in 50.432s`, `OK`, native `V99_FULL_EXIT=0`. Test log: `$env:TEMP\V99_FULL_ELLIOTT_REGRESSION.txt`, SHA256 `a218d75df84d2977c0fb15c5aca4f1b6e4290af08dcb83c289f2fb85224861a3`.
- Historical official source-verified V99 audit completed with native `V99_REPLAY_EXIT=0`; immutable generated diagnostic SHA256 `69a88a3e101d53ea4d84b1bad999de9482cf153fb6a9c1674cf0f40a604666a2`.
- GitHub V98 predecessor workflows: **Test, Workflow Permissions Policy, Research Evidence Refresh SUCCESS**. V99 CI requires independent confirmation after push; local tests alone are not a CI claim.
