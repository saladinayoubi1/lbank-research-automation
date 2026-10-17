# Elliott V70 — physically reverified legacy loss attribution and no-promotion decision

**Date:** 2026-10-16 UTC. **Mode:** isolated, read-only Bybit BTCUSDT/ETHUSDT historical Elliott economics audit. Draft PR #2673. Not new Elliott classifier, not prospective V52 scoring, not a Demo/Paper or live trade, not evidence of realised P/L.

## Why this gate matters

V37's frozen legacy historical research found a **positive training result** but **negative validation and previously inspected test results**. Positive fit to training must never hide that failure or become a profitable Elliot strategy assertion. V70 reconciles this claim **from the original physical trace and independent decimal QA**, not by trusting the V37 summary alone, then returns a recommendation **against promotion to Demo**. This is evidence about the older five-swing legacy implementation; it is **not** a backtest of the later strictly source-bound V52/V69 nested-wave hypothesis.

## Physical inputs independently verified

One-shot Laptop2 execution reopened and SHA256 verified:
- Original legacy `actual-fill-trace.json` and `market-results.json`, each pinned in V37's receipt and its independent decimal QA.
- `independent-decimal-qa.json`, whose own recorded trace/result hashes had to agree.
- V37 frozen `LOSS_ATTRIBUTION.json`, exact SHA256 `96d0322e416e1e7eb5587e08af8dff8b2e8590b677869808ff56d50b6548a024`.
- Every source trace trade's reported entry/exit reference, simulated quantity, costs and net P/L were independently recalculated using `Decimal`. Source quantities are parsed from JSON with `parse_float=Decimal`, avoiding binary floating point. Receipt aggregate arithmetic uses a **maximum eight-decimal-place USDT tolerance** only to address decimal context/order rounding; the numeric error margin is not strategy parameter slack.
- Recomputed per-symbol, per-partition, conservative/stress totals and paired exit reasons were cross-checked; alternate scenario trade pairs must match. Changed physical bytes are rejected by original pinned hashes.

## Results: historical simulated trades, NOT executed orders

| Previously inspected partition | Simulated positions | Conservative net (USDT) | Stress net (USDT) |
|---|---:|---:|---:|
| Train | 5 | +7.9633038243 | -12.0465623197 |
| Validation | 4 | -17.6745265834 | -33.5574683137 |
| Historically inspected test | 1 | -6.9028939465 | -10.8639662998 |
| **Total** | **10** | **-16.6141167056** | **-56.4679969332** |

- Overall win/loss: **4/6**, 4 take-profit exits and 6 stop exits in the old simulation.
- Per-simulated-position average net: conservative **-1.6614 USDT**, stress **-5.6468 USDT**.
- Modeled total friction: conservative **29.9789 USDT**; stress **79.7554 USDT**; stress adds approximately **39.8539 USDT** drag to total net results relative to conservative scenario.
- All three partitions have been inspected; **none is an untouched prospective holdout** now. The original model's modeled transaction costs, exit behavior and poor generalization each contributed to an unprofitable result. This report cannot isolate a single universally causal loss mechanism or infer real fills.

**Outcome:** `REJECT_PROMOTION_OUT_OF_SAMPLE_HISTORICAL_LOSSES`. This is a **scientific research promotion decision**; it is not a change to the app, signal engine or running paper bot.

## Reproducible evidence and tests

Independent script: `research/elliott_v70_frozen_loss_gate/loss_gate_v70.py`; native-discoverable synthetic regressions `research/elliott_v70_frozen_loss_gate/test_loss_gate_v70.py` and `tests/test_nexus_elliott_v70_economic_gate.py`. The focused 6/6 tests passed locally before publishing. They assert profitable training cannot override validation losses, inspected-test losses prevent promotion, stress-cost losses prevent promotion, all-historically-positive data still require unseen prospective validation, mismatched V37 physical receipt byte hashes reject, and no entry/Paper/Live permission exists.

The physical result was independently created once on the isolated second Windows laptop in `E:\NEXUS-QA\elliott-v70-legacy-loss-gate-20261016\V70_PHYSICAL_HISTORICAL_LOSS_AUDIT.json`, SHA256 `39a40bcbea2248f9b693ed529589d4c25d7e0e4b14c4f4c94748ea4369761a71`, tool exit code **0**. Initial scratch runs failed on float JSON decoding and overly exact Decimal aggregate comparisons, then were corrected and the physical results finally matched the independently frozen source. Neither the original legacy economics files nor frozen V52 rules were modified.

## Release boundary

- Bybit only, Research/Backtest/Demo-Paper only; **Live disabled**.
- No alteration to user journal, Laptop1 demo installation, remote agents, or paused VPS.
- **V52 frozen study** original parent 15m and child 3m, SHA256 `f853b8a5b896227998c30b0f5ea05a61364f1000fae610c767e81ad841c303e4`: Oct16–17 UTC warmup, **Oct18–Nov16 UTC end-exclusive** first scored window, subject to actual full-day archives and observation-lag checks. Legacy V37 profit/loss cannot be represented as scoring of these later waves.
- Draft PR #2673 is not merged; native full test suite and hosted CI on the new V70 exact commit must be checked before declaring global regression success.

**Next strategy research action:** Before proposing any revised Elliott trade, require a new, separately registered structural hypothesis with a non-leaking time-of-signal, fixed fee/spread/slippage schedule, actual fill or credible executable quote evidence and *unseen* validation. Do not select rules to make these ten already-inspected simulated trades profitable.
