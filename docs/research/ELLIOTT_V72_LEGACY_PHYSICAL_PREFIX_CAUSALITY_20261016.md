# Elliott V72 — Source-bound suffix-invariance audit of historical legacy five-swing features

**Date:** 2026-10-16 UTC. **Scope:** isolated Laptop2, Draft PR #2673, Bybit BTCUSDT/ETHUSDT previously inspected historical research. No Demo/Paper or Live changes. **Not** a new strategy, not proof of profitability and not V52 prospective scoring.

## Research question

V71 confirmed ten historical legacy simulated trades (20 fee/slippage-profile observations) use the physical archived 15-minute next-bar OPEN, with exit references consistent with source OHLC. Original numeric QA still explicitly lacked a complete independent raw-market feature-leakage audit. V72 tests a **narrow but falsifiable** necessary causality condition for the older Elliott-specific helper: do output features at the **original recorded entry-decision instant** remain bitwise identical when future source bars are appended or physically implausible high/low future extremes are substituted? In particular, was each event triggered strictly after its requisite pivot confirmation?

## Reproduction and source authority

The independent physical Windows study reopens:
- The original SHA-pinned simulator event trace, SHA256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c` (same V37/V71 receipt).
- Original existing verified archive loader of Bybit market 15m BTC/ETH data (2022-12-01 to 2026-07-31).
- Exact pre-registered original `nexus_causal_elliott_five_swing_features.py` and its dependencies, each source file rehashed against `PARAMETERS["feature_sha256"]` in the immutable original preregistration. **No original source file was changed.**

The ten **distinct** historical trade-decision indices are extracted directly from the frozen observation trace and required to match physically source-stamped 15m candle closes. For each decision `i`, an identical 1,024-closed-bar source prefix ending at `i` is processed three ways using the **same original** `build_lagged_elliott_five_swing_features`: (1) stop at `i`, (2) append 12 subsequent original archived closed bars, (3) append 12 future closed bars with drastically altered HIGH/LOW but same earlier bars. Every output series for all earlier timestamps is compared exactly, with NaN-aware equality. The recorded entry event must be active, present, and tied to an Elliott pivot confirmed **strictly earlier** than that decision. The test is read-only, requires original source hashes, and writes the historical receipt only once.

## Empirical historical result

- **10/10** original distinct simulated trade decisions match real archived completed 15m decision timestamps and an actual five-swing **feature event** in the frozen implementation.
- **10/10** original event pivots have `lagged_elliott5_confirmed_at < decision index` (strictly earlier right-hand confirmation).
- **10/10** 1,024-bar prefix feature outputs remain **unchanged** under appending 12 future actual 15m bars.
- **10/10** remain **unchanged** under extreme HIGH/LOW alterations confined to those 12 future bars.
- Hence for these ten historical event indices, **no future-suffix dependence or postconfirmation timing violation** was observed in the old Elliott-specific helper.

**Local physical receipt** `E:\NEXUS-QA\elliott-v72-prefix-future-leak-20261016\V72_PHYSICAL_PREFIX_PROOF.json` SHA256 `8060bb9cc8fe2ceb20e6051ca88d5cf11af917e9997dcf6609b4be46a5eb0a2e`. Script exit code 0.

## Focused adversarial tests

Eight standalone tests run locally **8/8 PASS** and committed to `research/elliott_v72_legacy_prefix_causality/test_prefix_v72.py`, with native discovery `tests/test_nexus_elliott_v72_prefix_causality.py`:
- Legitimate lagged synthetic features are invariant to appended/mutated future source bars.
- Deliberately dishonest last-future-close features **are detected**.
- A fabricated feature leaking altered later extreme highs **is detected**, even though append-only output remains unchanged.
- A fabricated current-bar-confirmed signal, noncausal at decision, is rejected.
- Short/invalid prefix fails closed, mismatched features fail equality.
- Altered source bytes change SHA.
- All module entry/Paper/Live flags remain disabled.

These regression fixtures are synthetic tests of the detector, **not actual-market trading outcomes**.

## What this does NOT prove

This is **not** a comprehensive line-by-line independent audit of the parent multi-timeframe `engine.build_features` 1h/4h context, historical archive publication time, all 128,544 timestamps, live bid/ask fills, orderbook, intrabar sequencing, the separate V52 15m/3m strict nested wave construction, or strategy profitability. A consistent prefix over these ten decisions is necessary evidence against look-ahead for the **specific feature helper** only. The legacy sample remains previously inspected and failed generalization and cost stress (V70). The research report must retain `source_level_all_engine_feature_leakage_proven_absent=False`, `future_V52_holdout_evidence=False`, `paper_eligible=False` and `live_enabled=False`.

The old legacy simulated trade cost accounting remains V70: conservative total -16.6141 USDT; stress total -56.4680 USDT. **No Demo promotion**.

## Next evidence gate

At the new HEAD confirm 8 native-discovered V72 cases, full native Elliott suite and hosted Windows/Ubuntu/macOS CI. Future research may independently verify all higher-timeframe feature as-of joins, but should not retune V37 trades or modify frozen V52 to make historical results profitable. The V52 prospective original remains SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, original 15m/3m, warmup Oct16–17 UTC, scoring Oct18–Nov16 exclusive. No actual forward score before physical daily archive observability.
