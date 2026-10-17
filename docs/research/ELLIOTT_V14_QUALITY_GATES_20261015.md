# Elliott v14 — causal quality repairs and outstanding market evidence

**2026-10-15. Research-only.** No new historical or forward Bybit candles were
scored, and no actual trade was placed. The parent v9, five-swing and ABC v11
source-bound results remain immutable and losing. Inspected 2022–July 2026
history cannot be treated as a pristine holdout.

## Implemented in this isolated diagnostic

- **Wave labeling:** reuse the frozen seven-confirmed-pivot reviewer; report
  explicitly that this is NOT a fully verified recursive 5-3-5-3-5 Elliott
  count. Missing evidence blocks Paper/Demo/Live promotion.
- **Entry:** demand a fresh CLOSED 15m cross above the confirmed fifth high,
  with the previous close at or below that level. Confirmed pivots must have
  become known before the decision. No buy occurs: a projected slipped
  decision close must not be confused with the actual next OPEN.
- **Stops and price scale:** compute a research-only structural stop at the
  confirmed correction low, rather than blindly using 1.5 times a smoothed
  candle high-low average. Report the prior 14 **True Ranges** as independent
  scale evidence, with no data-driven optimized threshold. Structural stop
  location can be too far away to justify a trade.
- **Transaction costs:** compare the prospective 2R target / structural-stop
  levels after fixed STRESS fees (25bps per leg) and slippage (15bps per leg).
  This is *feasibility*, NOT expected profit and NOT a no-fee backtest.
- **Feature semantics:** label the inherited 1h normalized candle-range gate
  correctly; actual traded-volume ratio is a distinct optional diagnostic.
  No newly optimized volume cutoff.
- **Causality:** require timezone-aware UTC aligned completed decision / 1h /
  4h closes, reject future/expired context and malformed numeric inputs.
- **Post-correction path:** require every completed 15m low and close from the
  correction pivot center through the decision, reject gaps, mismatched source
  closes/lows, *any* subsequent correction-low breach, and a previously consumed
  close-break. This closes the earlier stateless duplicate/invalidation gaps.
  It does **not** independently validate the full seven-pivot raw OHLC history,
  higher-timeframe feature values, prior true-range source hashes or provenance.
- **Valid zero values:** flat-bar True Range = 0 and zero traded-volume ratio
  are allowed; the aggregate 14-candle range baseline must remain positive.
- **Safety:** study_eligible is NOT entry_signal, paper_eligible, Demo or
  Live authority. Factory inventory, original execution engine, Laptop1
  paper journal and VPS are unchanged.

Files: nexus_elliott_quality_audit_v14.py,
tests/test_nexus_elliott_quality_audit_v14.py.

Native Laptop2 source tests: 28 unittest methods, 0 errors, 0 failures
(2026-10-15), staged at E:\NEXUS-QA\elliott-v14-quality-20261015.
Parent regression suites: 16 seven-pivot geometry + 26 closed-OHLC methods PASS on Laptop2.
Hosted exact-head CI must be checked separately.

## Still open before economic qualification

1. Verify recursive wave degree and actual subwave counts from completed
   original OHLC; today's seven-pivot reviewer cannot truthfully certify this.
2. Independently reconstruct 1h and 4h feature **values** as of each decision;
   a timestamp contract alone cannot certify numeric data provenance.
3. Freeze and collect untouched genuinely prospective public Bybit candle
   evidence with content hashes, no gaps, no duplicates, no forming candle.
4. Audit event-level signal-to-next-open delay, adverse gaps, MFE/MAE,
   stop/target ordering and reasons, True Range, actual volume, both fixed
   fee/slippage profiles, and net P&L. Independent QA must reconcile all.
5. Pre-register a separate NEW strategy before any market selection, then
   evaluate *future* closed candles. Do not retune the inspected folds.
   No automatic advancement to Demo; Live=false.

The current change improves validation contracts and prevents several unsafe
assumptions; it does **not** prove a profitable Elliott trading system.

System Map: DATA-20, DATA-21, RES-31, RES-32, VAL-40, QA-41.
Laptop2 research-primary; Laptop1 sole Paper writer; GitHub is truth.

## Independent re-audit disposition (2026-10-15)

- The initial 21 tests were insufficient: they did not supply the actual
  correction-to-decision bar sequence; the helper could previously classify
  a recovered structure despite a prior correction-low breach or first consumed
  breakout. The 28-test revision now rejects both with synthetic regression.
- The revised observer remains an *advisory* research diagnostic, not a
  source-verified market evaluator. The supplied path and claimed higher
  timeframe flags are caller-originated; independent raw source reconstruction
  and a fully valid recursive Elliott count remain outstanding.
- A structurally anchored stop is **not inherently profitable or better**:
  it may create excessive risk distance (measured in prior mean True Range).
  Historical optimal risk tuning is prohibited. No qualifying strategy run.
