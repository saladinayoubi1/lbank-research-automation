# NEXUS Elliott V24 — entry/exit integrity firewall, no hindsight tuning

**Research date:** 2026-10-15. **Result:** `PASS_SYNTHETIC_ENTRY_EXIT_SAFETY_AUDIT`, not a trading result. Native Laptop2: **22/22** dedicated tests and **216/216** full Elliott-specific regression tests PASS on branch HEAD `3999ebca1f30b1654970d42c3440cbcf2dcc69ed`.

## Problem

The inspected Elliott five-swing historical simulation has **some winning trades** but net losses under both fixed transaction-cost profiles. The historical evidence is not pristine, recursive wave degrees have not been independently verified, and future Bybit source continuity / entry+exit receipts are not yet sufficiently certified. **A winning historical entry cannot be used to tune the entry/exit rules retroactively.**

Existing pre-registered V17 paperless research outcome model remains unchanged:
- Closed 15m breakout above previously certified fifth high, then hypothetical **next candle OPEN**, never a decision-close broker fill.
- Fixed structural correction-low stop, 2R target, 64 completed 15m-bar hold maximum, with conservative/stress cost profiles and Decimal-precise sizing.
- The stop wins if both protective stop and take-profit are touched inside the same OHLC candle, because the intrabar order cannot be inferred.
- Gaps through stop cause **worse** execution than the nominal stop; favorable target gaps do not create free upside.
- On missing/partly formed candles, output `AWAITING_MORE_CLOSED_BARS` and `net_pnl=null`, never fake zero PNL.

## New separate forensic gate

`nexus_elliott_entry_exit_integrity_v24.py` independently reconstructs the next-open entry, source chronology, original fixed V17 quantity caps, cost/fee ledgers, stop-versus-target priority, gap-through stop and time-limit exit from the supplied closed OHLCs and compares against V17's frozen numerical receipt. **It does not authenticate the provider or replace source-bound V14/V15.**

### Entry-error controls

1. If the first next open is **at/below correction low**, the V17 model must return **NO ENTRY** with null PNL.
2. If the decision candle closes above fifth high, **but the next open has already returned to or below fifth high** (while still above correction), set `NEXT_OPEN_REENTERED_PRE_BREAKOUT_RANGE`, and set `prospective_price_path_entry_gate_passed=false`. The original V17 hypothetical fill/P&L is still preserved, with an explicit warning; **it is not selectively removed from previous samples**.
3. An otherwise price-path-valid next open gets the separate *advisory* true flag only; this is **not** a Paper/Demo/Live authorization because provider authentication, complete historical source continuity and true recursive Elliott labeling remain open.
4. Reject any ambiguous, incomplete or misaligned 15m UTC source bar, and reject duplicate event IDs or repeated same symbol/decision/profile to prevent counting one winning event twice.

### Exit-error controls

- Never accept a stop/target conflict as guaranteed profit: if both high and low cross the frozen bracket in the same bar, record **stop-first** and an intrabar sequencing warning.
- If the stop is hit in the entry candle, annotate that high/low sequence is unobservable from OHLC.
- If an exit bar opens below correction low, independently demand that stop reference equals the worse open, not the nominal stop price.
- If a bar opens beyond target, cap the positive reference at the frozen 2R target.
- Only call a result `EXITED` if the proper completed exit bar, reason, reference exit price, slip, both fees and 46-digit Decimal net PNL all reconcile. The holding period can only expire on the **64th completed** bar.
- An unclosed/pending event stays **null PNL**, not an implicit win or zero-loss. A supplied receipt with forged net gain or switched stop-to-target reason is rejected.
- Risk budgeting is nominal, **not guaranteed** when an opening gap through stop occurs.

## Testing

- `tests/test_nexus_elliott_entry_exit_integrity_v24.py`: **22 synthetic-only adversarial methods**, all PASS on Laptop2.
- Full command from the repo on Laptop2:
  `python -m unittest discover -s tests -p test_nexus_elliott_*.py -q`
  Output at HEAD `3999ebc`: `Ran 216 tests in 5.891s — OK`.
- Tests explicitly include manufactured positive targets, adverse gaps, same-bar stop+target conflict, broken future chronology, false receipts, premature exits and duplicate identities. **These are not market-trade results**.

## Elliott strategy path, with honest promotion gates

**Research variant:** wave-5 closed-breakout continuation with correction-low invalidation, same preregistered 2R/time-limit mechanics, and an advisory next-open breakout-retention check. A seven-pivot sequence is **not equivalent** to a causally certified recursive Elliott 5-3-5-3-5 impulse and ABC correction; independent subwave/wave-degree proof remains required before describing it as a verified Elliott strategy.

Required path: provider-authenticated raw Bybit BTC/ETH trade data → UTC-contiguous 15m/1h/4h source/model provenance → independent causal wave identification and complete first-break proof → **predeclared** entry-quality and stop/target study → truly new forward outcomes with trade count, net expectancy, MAE/MFE, costs and uncertainty → external QA → *separate* approval for any Demo experiment. All under Bybit-only Demo/Paper restrictions; Live remains disabled.

No new historical fitting, backtest rerun, parameter optimization, new profit result, actual position, automated strategy signal, order or changes to Laptop1's Paper writer, 500-USDT paper reference, legacy archive or paused VPS. PR #2673 remains **Draft**; any new rule must be frozen *before* scoring a future dataset rather than chosen after observing winners.

**Source files:** `nexus_elliott_entry_exit_integrity_v24.py` and `tests/test_nexus_elliott_entry_exit_integrity_v24.py`.
