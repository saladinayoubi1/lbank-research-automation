# Elliott V45–V49 — 5-day source-verified 1m expansion and strict child-witness gate

**Date:** 2026-10-16. **Research device:** Laptop2 `DESKTOP-F4SA4VL`. **PR:** #2673 Draft.  
**Scope:** Official Bybit Spot BTCUSDT/ETHUSDT raw trades, 2026-10-08 inclusive through 2026-10-13 exclusive (UTC), **historically inspected** data. Neither the user’s 500-USDT Paper balance nor Live authority, laptop1, journal, old archives or paused VPS was changed.

## V45: fresh immutable 1m source archive

A separate directory `E:\NEXUS-QA\elliott-v45-source1m-oct08-12-20261016` consumed ten SHA-pinned official daily raw-trade files from the V33 source manifest, with full gzip-to-EOF and causal raw timestamp/CSV original-row ordering. No missing minute was filled synthetically.

| Official source | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Verified raw trades | 4,472,750 | 1,445,019 |
| Source-bound UTC 1m candles | 7,200 | 7,200 |
| Cross-checks to separately audited V33 15m/H1/H4 bars | 3,150 | 3,150 |
| Mismatched OHLCV values | 0 | 0 |

The V45 output is a new stand-alone dataset, not a splice with the protected V20 or earlier V41b parquet. V41b remains a separate Oct13–14 archive.

## V46: independent full raw-to-1m oracle

A second standalone implementation re-read and re-hashed all ten original Bybit trade archives, rebuilt every 1m bar by streaming raw trade prices, volumes and counts, and independently compared to V45 without invoking the V45 builder:

- **5,917,769** original trades independently traversed
- **14,400** 1m candles, time grids exact
- **72,000** OHLCV numeric field comparisons: zero discrepancies
- **14,400** per-minute trade-count comparisons: zero discrepancies
- Both pairs and final receipt marked PASS.

## V47/V48: parent anchors and actual source-bound ETH candidate

The unchanged 15m width-3 strict pivot state was separately reconstructed on this five-day, independently verified source:

| Fixed diagnostic | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Accepted 15m pivots | 76 | 79 |
| Independently verified strict 1m source origin | 69 | 72 |
| Ambiguous or nonstrict minute pivot origins | 7 | 7 |
| Strict 9-anchor impulse + zigzag ABC *parent geometry* candidates | 0 | **1** |

The **single ETHUSDT parent geometry** arose 2026-10-10 08:45 through 22:45 UTC, with nine accepted 15m anchors at indices `227,230,234,250,260,270,273,279,283`. All nine map uniquely to causally confirmed strict physical 1m pivots. These mapped minute indices are `3405,3451,3512,3760,3902,4060,4097,4187,4246`. This is a **parent-level geometry witness only**, not a confirmed degree-separated 5-3-5-3-5 + ABC wave count.

The unchanged strict 1m extrema census per eight parent legs yielded observed alternating *interior* pivot counts `6,8,10,18,19,4,8,10`, whereas the predeclared bounded V40 child segmentation expects `4,2,4,2,4,4,2,4`. These data are not retrospectively pruned or thresholds re-fitted.

## V49: deterministic, non-retuned child-witness proposer

Added `research/elliott_v49_fixed_child/propose_nested_v49.py` and 12 offline synthetic guards to Draft PR #2673, with native CI shim. The frozen research rule includes **every** strict width-3 1m local extremum in each parent leg, compressing only consecutive same-kind internal extrema by the more extreme replacement rule, with no arbitrary skipping; exact predeclared 5-3-5-3-5 plus ABC child counts are required before calling the independent V40 full source validator.

- **12/12** synthetic regression cases passed locally, including positive fully source-bound bounded one-child-degree witness and future/timing/price/parent mismatch rejections.
- The real 2026-10-10 ETH case was rejected at its **first leg**: expected 4 interior child extrema, observed 6 under the fixed predeclared model, `CHILD_COUNT_MISMATCH_LEG_0`.
- This rejection is **not proof that there is no Elliott wave**; it identifies missing defensible *degree separation* under the presently frozen one-degree model. Do not retroactively select whichever four pivots give an attractive backtest.
- All outcomes remain `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`, `recursive_complete=false`, `new_pnl=null`.

## Laptop2 QA receipts and SHA-256 evidence

All files below remain on Laptop2 under `E:\NEXUS-QA\` and are **not** claimed to be GitHub-hosted JSON attachments.

| Local receipt path | SHA-256 |
|---|---|
| `elliott-v45-source1m-oct08-12-20261016/PROVENANCE_RECEIPT.json` | `5deb88cf83f80e5926e9f83375c1c80879c57883e9273efac6884a32c1c6e385` |
| `elliott-v46-independent1m-oct08-12-20261016/INDEPENDENT_ONE_MINUTE_QA.json` | `c4cfa9898a77df0b50806402e697610d01beb543a57c81b3a3658d97f0bff5bf` |
| `elliott-v47-parent-minute-oct08-12-20261016/PARENT_MINUTE_ORIGIN_QA.json` | `98923c7cc34723b39aef00ec553f19a18b803da9738a8e0877f13cdf3ecc4bee` |
| `elliott-v48-nested-candidate-oct08-12-20261016/SOURCE_BOUND_NESTED_CANDIDATES.json` | `d8af71e184451d48044e0bba906be33603c6791b8c5eb8f25b4238e8990f22ea` |
| `elliott-v49-fixed-child-proposer-20261016/REAL_FIXED_CHILD_QA.json` | `96165e000ac129b9cd7419251e181d97c8b2300966cf57915b95d55d551d3bd6` |

**Next research gate:** establish an independently preregistered, causal *degree assignment* method on complete lower/higher timeframe source bars and test it on genuinely unseen post-registration market data. Continue to refuse unknown subwave counts, retrospective path trimming, fill assumptions, and premature paper promotion. Require quote/fill provenance, conservative fees/slippage, and independently validated stop/target ordering for any later economic test. Live always prohibited.
