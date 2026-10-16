# Elliott V78 — Source-bound stop-bar OHLC ordering ambiguity

**UTC date:** 2026-10-16. **Project:** NEXUS, isolated Laptop2, Draft PR #2673, Bybit Spot historical legacy Elliott five-swing research only. **No executable orders, new P/L, changed strategy, demo, VPS, or live-trading permissions.**

## Motivating defect in research interpretation

The V77 physical 15-minute archived source first-touch audit validated all *twenty* conservative/stress trade-profile paths from the ten original, already-inspected simulated trades. **No recorded trade remained open across a previous bar that had already touched its own stop or target**. The two cost profiles had different stop/target levels; **three distinct ETH trades legitimately exited on different bars**, without changing original parameters.

However, `full_hold_favorable_R` in V77 includes the **final stop bar's entire HIGH**, whose ordering relative to that bar's LOW is **not known from 15m OHLC**. Treating a high of +1R or more on the same stop bar as an executable profitable exit before the stop would invent the intrabar price path, irrespective of whether the original target was reached. This is a materially different question from V77 first-touch integrity.

## Actual original source-bound result

V78 reopens **the unchanged immutable source-bound V77 physical report**, SHA256 `6e842b71af41f43a78c3e70c3e148ee1896153123aad8e4e2a8cc8f7660806e3`; it requires the original pinned legacy trace SHA, 20 verified profile paths, ten unique historical simulated trades, zero earlier-bar exit violations and no Demo/Live eligibility. It calculates two *separate* columns: `preexit_favorable_R` from **only strictly earlier fully completed 15m bars**, versus `full_hold_favorable_R` including the final stop bar. These cannot be conflated.

| Historical simulated exit audit | Outcome |
|---|---:|
| Original stopped positions | 6 distinct trades |
| Cost-profile-specific stop paths | 12 |
| Verified +1R favorable HIGH on strictly **earlier** source bars among stopped paths | **0/12** |
| +1R favorable HIGH appearing only with the final stop bar, **order unknown** | **2/12** |
| Distinct historical trades implicated by those two profile observations | **1 ETHUSDT validation trade** |
| New demonstrated executable +1R pre-stop exits | **0** |
| Changed position records or new prospective score | **0** |

For the one implicated ETH validation trade the cost profiles show full-hold favorable excursions around **+1.37R** and **+1.97R**, but both exits are stops on the entry bar; there is **no earlier fully completed holding bar**, and 15-minute OHLC cannot show whether the bar's high came before or after the stop low. Thus V78 classifies both observations `terminal_stop_bar_intrabar_1R_timing_unresolved=True`, explicitly **not as evidence for tightening/trailing stops or earning a +1R profit**. Using a later high after stop to infer a winning trade would be an invalid counterfactual.

**Independent immutable local receipt:** `E:\NEXUS-QA\elliott-v78-exit-bar-sequence-ambiguity-20261016\V78_SOURCE_BOUND_STOP_BAR_AMBIGUITY.json`, SHA256 `78467e29391ada334fb86d0e1c9072ef91e869f0c2168ee2864ba9f0b34a0915`; one-shot script exited `0` on Laptop2. The original source OHLC and its V77 cryptographic evidence were not changed. V78 is a **downstream audit of V77's already physically verified source bars**, not a new independent gzip fetch.

## Defensive tests

Standalone Python-only `research/elliott_v78_historical_stopbar_ambiguity/audit_v78.py`; focused `test_v78.py`, discovered by `tests/test_nexus_elliott_v78_stopbar_ambiguity.py`. **11/11 focused tests PASS locally**, including: rejecting a modified receipt hash, rejecting false Live permissions, preserving missing prior bars on one-bar stopped trades, flagging +1R on the terminal stop candle as timing-unknown, distinguishing strictly prior +1R from same-terminal +1R, rejecting corrupt exposure or prior > full OHLC high, and verifying nonexecution. Synthetic tests demonstrate the classifier is not hardcoded to treat all prior gains as absent.

**Global acceptance:** full native Elliott suite and exact-HEAD Windows/Ubuntu/macOS hosted CI must be checked before reporting V78 as globally passing.

## Scientific and operational boundaries

The old legacy ten-trade model is still historical and loses **−16.6141 USDT conservative** and **−56.4680 USDT higher-cost stress** after modeled costs; validation was negative even before fees/slippage. V78 neither optimizes thresholds nor rescues strategy profitability. Nothing here independently proves intrabar tick order, executable bid/ask, actual fills, or causal effectiveness in unseen data.

The original V52 Bybit Spot BTC/ETH future 15m-parent/3m-child protocol SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4` remains untouched. Oct16–17 UTC warmup, Oct18–Nov16 UTC end-exclusive prospective scored source window; Oct18 official UTC daily archive can only be physically complete **no earlier than Oct19 00:00 UTC**, subject to actual publication delay and V59/V60/V69 as-of observability. No source may be backdated.

**Decision:** no Demo promotion, no new entry/exit, no live orders; keep the PR Draft until explicit authorization and all tests pass. The useful future proof for intrabar ordering requires actual timestamped tick/orderbook data with authentic source arrival evidence, not another OHLC-derived guess.
