# NEXUS Elliott V77 — source-anchored first-touch audit of historical exits

**Date:** 2026-10-16 UTC. **Scope:** isolated Laptop2 retrospective Bybit BTCUSDT/ETHUSDT 15-minute research, Draft PR #2673. **No live or demo orders, no new P/L, no modification of the old strategy or prospective V52 study.**

## Purpose and difference from V71

V71 compared the final simulated exit bar with the historical Bybit source OHLC but did not examine every **earlier** bar during position exposure. A trade could have crossed its stop or target earlier than reported and still pass a final-bar-only assertion.

V77 first re-runs V71's checks against original frozen source hashes and its verified 15m archive. It then scans **all physical source bars from each recorded entry to exit**, testing that no prior bar crosses the scenario-specific stop or target, no 64-bar time-limit expiry was ignored, and the final bar's recorded exit reason and reference price agree with the frozen stop-first model.

## Source provenance

- Original frozen legacy trade trace SHA256: `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`.
- Original market result SHA256: `02f96ca942091d882be7ba87547cd0b6f9c2e3e440fe4cc6e98b3e010332d2fc`.
- Immutable V37 receipt SHA256: `96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024`.
- Verified historical Bybit 15m archive: `C:\NEXUS\research-cache\replay-canonical-37681826492\archive`, as originally bound in V71.
- Local final one-shot immutable report: `E:\NEXUS-QA\elliott-v77-exit-first-touch-20261016\V77_PHYSICAL_FIRST_TOUCH.json` SHA256 `6e842b71af41f43a78c3e70c3e148ee1896153123aad8e4e2a8cc8f7660806e3`, process `EXIT_CODE=0`.

## Physically reverified historical outcome

| Check | Result |
|---|---|
| Distinct historical simulated positions | **10** |
| Conservative + stress cost-profile-specific complete paths | **20** |
| Positions erroneously held past an **earlier** stop or target touch | **0** |
| Profile-specific stops | **12** |
| Profile-specific targets | **8** |
| Distinct positions with different exit bars between cost profiles | **3 of 10** |
| Original full V71 source/timestamp and final OHLC proof | **Repeated and passed** |

**Necessary correction during test authoring:** an initial check incorrectly assumed the conservative and stress cost profiles should exit on the same bar; that was disproved by physical original data. The frozen scenarios have *different stop and target levels* due to their distinct slippage/risk-budget conventions. For three ETH trades, the scenarios legitimately reach their different exit levels on different bars. The final V77 version requires the same original entry and exit **reason class** across profiles but independently checks the correct profile-specific first-touch bar for each. No original data or trading parameters were altered.

## Regressions

`research/elliott_v77_legacy_exit_first_touch/first_touch_v77.py` is a **standalone read-only** audit, not imported into the running app. Its original 15m loader is required only for an explicit physical replay; native tests use synthetic Pandas OHLC.

`research/elliott_v77_legacy_exit_first_touch/test_first_touch_v77.py` passed **10/10** local focused cases: late target/stop, delayed 64-bar exit, stop-first ambiguous terminal candle, adverse stop gap, wrong terminal exit, malformed OHLC, inconsistent bar exposure, correct final-bar first-touch, and nontrading flags. `tests/test_nexus_elliott_v77_first_touch.py` enrolls these tests into repo discovery.

**Global acceptance pending until separately observed:** exact V77 HEAD full native Elliott suite and Windows/Ubuntu/macOS hosted CI. Previously verified V76 `8c2027bdb60178b0ff0407010b0d95d2483440e2` had 534/534 native tests PASS and all hosted CI SUCCESS; this alone is not proof of V77's status.

## Limits and next gate

Full-bar low/high does **not** establish subbar touch ordering, executable bid/ask, venue order fills, market impact, historical archive availability at each simulated entry instant, the entire feature-engine causality, or profit. The original legacy strategy remains training-positive yet validation/test-negative: conservative total simulated **−16.6141 USDT** and high-cost stress **−56.4680 USDT**. Do **not** promote to Demo or retrospectively retune to improve old trades.

Frozen original V52 15m parent/3m child protocol SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`, Oct16–17 source warmup, Oct18–Nov16 UTC end-exclusive future research scored window unchanged. The Oct18 daily scored archive cannot finish before Oct19 00:00 UTC plus publication lag, and any future source must meet V59/V60/V69 physical availability checks. **Live disabled; Laptop1 Demo, paper journal and paused VPS untouched; PR Draft/unmerged.**
