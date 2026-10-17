# Elliott V73 — Physical Bybit historical H1/H4 as-of provenance audit

**Date:** 2026-10-16 UTC. **Scope:** isolated Laptop2 research, Draft PR #2673, *historically inspected legacy five-swing candidate* only. **Not** a newly profitable Elliott strategy, prospective V52 scoring, real-time quote/fill, or demonstration that every feature is look-ahead free. Demo/Paper and VPS untouched, Live disabled.

## Specific gap tested

V71 verified the next-15m-open simulated entries and stop/target exits for the ten original legacy simulated trading decisions against complete source-archived 15m Bybit OHLC. V72 physically checked the older Elliott-specific 15m feature helper at those same ten decisions: append/tamper 12 future bars does not change past output and each wave pivot was confirmed strictly before the event.

V73 asks one additional and **narrow** question: does the unchanged historical composite engine's `_closed_asof` merge for `h1_vol_ok`/`h1_compression` and `h4_up`/`h4_range` select only **physically finished 1h/4h candles**? It independently checks every source timestamp and the latest eligible close rather than trusting merge output alone.

## Source and method

- Reopen the original **Bybit historical verified OHLC archive**, 1h and 4h, for BTCUSDT/ETHUSDT using the original verified loader. Original span: 2022-12-01 through 2026-07-31 inclusive.
- Recheck SHA256 of the frozen legacy observed trade trace `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`. Obtain ten distinct (symbol, partition, trade index) decision timestamps; the two cost profiles cannot disagree on a decision's timestamp.
- Import the original *unaltered* `nexus_composite_strategy_research._closed_asof` with source hashes pinned by the original immutable Elliott preregistration; independently recompute the original 1h/4h higher-timeframe context formulae.
- For each trade decision timestamp `T` and each interval (60, 240 minutes), independently find latest source **OPEN + duration ≤ T** and next parent **OPEN + duration > T**. Check the physical archive is contiguous UTC.
- Evaluate the unchanged original as-of merge three ways: source ending on last eligible closed higher-timeframe bar, original source plus eight genuinely later parent bars, and source plus the same eight future bars with drastically changed highs/lows/closes/volumes. Its output must equal the independently calculated latest-closed-parent context in every case; the future unfinished parent candle is never considered known at `T`.

This reproduces the existing code without modifying it. The local one-shot output is written exactly once and SHA-hashed.

## Physical historical outcome

| Invariant | Actual physically reverified result |
|---|---:|
| Distinct original legacy simulated entry decisions | **10** |
| One-hour context checks | **10/10** |
| Four-hour context checks | **10/10** |
| Original as-of engine vs independent latest completed candle oracle | **20/20 match** |
| Real future parent bars appended, earlier output unchanged | **20/20** |
| Extreme changes only to eight future parent bars, earlier output unchanged | **20/20** |
| Accidental use of next unfinished 1h/4h parent candle in these examples | **Not observed** |

Concrete illustration: for historical BTCUSDT decision **2024-10-07 00:45 UTC**, the available latest 1h candle was **23:00–00:00 UTC**, next one closed at 01:00 UTC. The latest 4h candle was **20:00–00:00 UTC**, next closed at 04:00 UTC. Neither still-open candle could legitimately enter the context at 00:45; both H1/H4 original engine values matched the independent oracle.

**Immutable physical receipt:** `E:\NEXUS-QA\elliott-v73-parent-timeframe-asof-20261016\V73_PHYSICAL_PARENT_ASOF.json`, SHA256 `befb22bf6107f60e93c12f4b39c19ef32d277d60f6a5fa1a57ba95f9ff6b3e8f`. The physical source replay exited successfully and reported `parent_checks=20`, `distinct_decisions=10`.

## Adversarial regression and final limits

- `research/elliott_v73_parent_source_asof/parent_asof_v73.py`: portable pure as-of checker; imports the original private archived loader only inside the explicit physical replay entrypoint, never in normal native suite.
- `research/elliott_v73_parent_source_asof/test_parent_asof_v73.py` and `tests/test_nexus_elliott_v73_parent_asof.py`: **10/10 focused tests passed locally**. They include legitimate 1h/4h completion and exact boundary, malicious next/future-bar merger, corruption activated only by future high changes, missing source hour, naive decision time, bad interval, insufficient causal parent history, non-executing flags. A forged merger is **rejected**, proving that invariance checks are not unconditional.

**Limitations:** This test covers the original 1h/4h as-of merge and four higher-timeframe context output fields at **ten already-observed legacy trade decision instants**. It does **not** rule out all potential leakage elsewhere in `engine.build_features`, incomplete-current 15m bar issues elsewhere, full-archive publication timestamps, tick-level fill execution, the new 3m V52 nested-wave model, or any profitable performance. Original V70 conservative training +7.9633, validation -17.6745, inspected test -6.9029, total -16.6141 USDT; stress -56.4680 USDT. Therefore old Elliott remains **ineligible for Demo promotion**.

Frozen original V52 SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`; warmup source UTC Oct16–17, scored window from Oct18 through Nov15 inclusive (Nov16 UTC exclusive), only after physical official archive observability and V69 as-of gating. V52, Laptop1 paper journal, demo install, runner and paused VPS unchanged. Exact-head full-suite and GitHub CI require separate results and should never be inferred from focused-test success.
