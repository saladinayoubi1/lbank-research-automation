# NEXUS Elliott V105 — causal wave-position and conservative exit diagnostics

**Status: research-only, synthetic-fixture validation, no market samples or trades.** The purpose of V105 is to prevent a methodological error: using a *later, fully confirmed five-wave Elliott-like structure* to claim an earlier wave-2/wave-3 entry. V105 does **not** prove the market's actual Elliott wave position or a profitable strategy.

## What V105 fixes in entry timing

Previous V101 validates a full six-vertex, five-leg, *restricted non-diagonal/non-truncated Impulse skeleton* only after its last wave-5 coarse pivot is right-confirmed. That is an **end-of-pattern** confirmation. It cannot retrospectively be used to claim an order executed near the earlier wave-2 or wave-3 centers. Source-derived extrema are historical pivot centers; right-confirmation timestamps are the earliest decision times.

Implementation `research/elliott_v105_causal_position/position_v105.py` adds a separate **nine-consecutive-pivot** reversal-context screen on top of the frozen V101 seven-event geometry and V100 causal source ledgers. Three *prior* confirmed coarse observations and six impulse vertices are used, with no skipped or pruned fine-scale pivots.

For a hypothetical bullish impulse beginning at a LOW pivot, the three prior points are HIGH–LOW–HIGH and require strict **lower high** followed by a **new lower low** at the proposed impulse origin. The downward impulse is the exact mirrored price-direction transform. These are only a *deliberately narrow reversal-contour* necessary screen; classic Elliott impulse wave-position certification requires additional multi-degree evidence. Each predecessor must be confirmed before the first proposed impulse center's confirmation; the full signal cannot exist until the wave-5 right-confirmation instant. V101 hard failures, source index/time mismatches, future confirmations, count mismatches and missing context cause rejection.

## Counterfactual first-minute risk gate — not an order/fill engine

Only after the original wave-5 confirmation time does an **illustrative** first post-confirmation minute become eligible for *retrospective* assessment. The next minute OHLC is not known in full until that minute closes. V105 refuses evaluating its extrema at the earlier decision time, so no future bar can inform a past entry.

The only example reference price is that **already completed minute's OPEN**, explicitly **not** an actual executable entry fill. A hypothetical defensive reference is the confirmed wave-4 center price; if the following open is on the wrong side of that reference, the study abstains instead of manufacturing positive risk. With a strictly valid synthetic context, a fixed, arbitrary illustrative target is twice the projected distance to that defensive reference (2R). This is **not** a calibrated take-profit, an Elliott-derived target or evidence of expected positive return.

On a single completed minute, if BOTH the protective stop and target levels are touched by OHLC, the result is `BOTH_TOUCHED_ASSUMED_STOP_FIRST_NO_INTRABAR_SEQUENCE`; the order of intraminute extrema is not guessed. If only one is touched, it is tagged as **hypothetical** stop/target touch; otherwise, **NO_EXIT_IN_FIRST_CLOSED_MINUTE**, not an invented completed profitable position. All cases unconditionally return **zero real entries or exits, no P/L**, with `entry_signal=false`, `paper_eligible=false`, `live_enabled=false`.

This single-bar diagnostic is NOT a complete multi-bar simulator and excludes commissions, spread, slippage, price impact, latency and unresolved future exits. Do not promote its labels as Bybit Demo opportunities.

## Frozen source and deployment boundaries

V105 inherits V101's untouched future Bybit **public Spot** BTCUSDT/ETHUSDT one-minute window **2026-11-16 00:00 to 2026-11-30 00:00 UTC exclusive**. It verifies the Git-locked V104 source-intake challenger (commit `cd4421fe6a38e7ed4177e74e3f3a73e0506df279`, source protocol SHA256 `ddac100a49f290a81e51c53f9de0e0706965d1269684881a72b3bf1ee927686f`) before freezing its own rulebook.

V105 static future research protocol: `docs/evidence/elliott-v105-causal-position-20261017/V105_FROZEN_CAUSAL_POSITION.json` SHA256 **`40d2b2d582a782205e115ddceacc07342f69c41111b6f6f4681785798f343e24`**, with **0 real future market rows accessed, 0 real patterns, 0 positions**.

V105's synthetic QA proves a correctly ordered bullish and bearish necessary-context geometry may pass the research screen but will *never* certify an Elliott market wave or place a trade. Adversarial tests cover predecessor trend, invalid impulse geometry, missing or future-confirmed pivots, backdated or delayed decision points, nonclosed following OHLC, invalid prices, illustrative risk invalidation, one-stop/one-target touches and same-bar stop-priority.

**Scientific conclusion:** a past-pattern contour and a future-pattern endpoint are not an actionable early-entry strategy. Next research must separately define and preregister an **early observable partial-wave hypothesis** (with explicit false positives, no full-wave hindsight), then evaluate on truly unseen data using Bybit-specific costs and a complete conservative execution model. This is independent of—and must not modify—the V52 October 18–November 15 prospective protocol.

PR #2673 must remain Draft/unmerged. GitHub is the source of truth. Laptop1 Demo, all original research files and paper journal remain untouched; no Live Trading or remote order connectors.

## Verified QA and release gates (2026-10-17)

- **21/21 V105 synthetic causal/context/exits tests PASS**, `V105_DEDICATED_EXIT=0`. This includes mirrored bullish/bearish context, rejection of future wave-5 leakage, inability to treat an unclosed first OHLC as a fill, invalid risk, wave-4 stop, gap beyond stop, simultaneous stop/target stop-first accounting, and explicit no order paths.
- **944/944 full Elliott tests PASS** on Laptop2, `Ran 944 tests in 59.743s`, `OK`, `V105_FULL_EXIT=0`. The local full-suite log `$env:TEMP\V105_FULL_ELLIOTT_REGRESSION.txt` has SHA256 `23210ca3c3acf1c3de34f516eee76ff88ab4f7f3e2e2b4c539a75482fb5c0e11`.
- Frozen source-locked future research manifest SHA256 `40d2b2d582a782205e115ddceacc07342f69c41111b6f6f4681785798f343e24`; native `V105_FREEZE_EXIT=0`. Exactly **zero** market observations were evaluated for V105.
- Predecessor GitHub CI for V104: Research Evidence Refresh and Workflow Permissions Policy **success**, Test **in progress** when last checked. That is not a V105 CI outcome; remote V105 acceptance requires subsequent independent verification.
