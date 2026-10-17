# Elliott V16 — frozen entry economics and structural-stop diagnostic

**Source-bound verdict: PASS_FROZEN_ENTRY_AND_EX_ANTE_RISK_GEOMETRY** (2026-10-15), DESKTOP-F4SA4VL research laptop. The review is **READ-ONLY and NOT a new market backtest or a counterfactual P/L trial**.

## What was measured

The source-bound old five-swing actual-fill trace, exactly SHA-256 `c734d9abd0dd8a18fe4269a15b8eceddf91643d8943ddb3bc851311772f2373c`, contains **10 independent admitted entries** (BTC 2; ETH 8) replicated under both *conservative* (10bps fee, 5bps entry/exit slippage per leg) and *stress* (25bps fee, 15bps slippage per leg): **20 profile entry observations**. No replay of earlier historical first-event producer, no newly discovered event, and no simulated future exit outcome.

The research checker [frozen_entry_risk_audit.py](./frozen_entry_risk_audit.py) independently verifies for every observation:

- The original exact entry-decision and **next OPEN** timestamps/bar indices, the archive's observed next-open price (not an actual exchange trade), and the slipped modeled entry in the old frozen trace.
- Original stop = modeled slipped entry minus **1.5 × mean completed 15m high-low**, as recorded by the parent. This parent measure is *not* proper True Range or Wilder ATR.
- Elliott parent correction pivot index/low against byte-hash-bound raw source 15m candles; BTC SHA `c3afe92899dda8fe52937c955323cc8e04bf8f200a68eb8651e55d6020981226`, ETH SHA `ce603440650d0022b1a17a7922da743a3b6219ba9afd89ad4362b70fbe3bbfa1`.
- Proposed structural correction-low stop distance vs original ATR-proxy stop distance and a separately recomputed true-range reference for the **same 14 completed preceding bars**. If the next-open reference were at/below structural stop, the checker would reject an eligible projected entry rather than claim a valid fill.
- Pure **ex-ante** 2R hypothetical target, both fixed fee/slippage profiles and their corresponding *conditional* breakeven target-hit ratios. No inference of outcome or simulated P/L. Reference sizing uses only a separate research cell's 10,000 USDT / 10 USDT fixed stop budget with a 1,000 USDT cash cap, **NOT** the owner's 500 USDT Paper balance.

All 12 new native synthetic tests PASS after fixing a contradictory synthetic fixture (the correction low had accidentally been placed inside the previous-14-candle range while average range was hardcoded to 2; no production code or source arithmetic was weakened).

## Numerical observations — medians across 10 original entries per profile

| Property | Conservative | Stress |
|---|---:|---:|
| Structural stop distance / original stop distance | 2.695× | 2.893× |
| Structural stop distance / previous-14 True Range mean | 4.042× | 4.339× |
| Hypothetical target-hit rate required to break even **IF** full 2R target/structural stop were realized | 39.08% | 47.37% |
| Historical next-open gap relative to entry-decision close | +0.000112% | +0.000112% |

Range for structural/original stop risk: conservative 1.911–3.872×; stress 2.044–4.105×. Range for hypothetical breakeven target hit fraction: conservative 37.76%–42.72%; stress 44.29%–55.33%. The future market **did not necessarily touch** a 2R structural target before a stop; no such assumption is made.

## Interpretation and next falsification gate

1. **Confirmed:** the structural stop proposed in V14 is materially wider than the stop used in the losing old five-swing study on every admitted entry. Just switching to this stop is neither a proven risk reduction nor evidence of improved expectancy.
2. **Not established:** target-hit frequency, drawdowns, gap-at-exit, slippage feasibility, prospective net positive expectancy, or whether the 2R target is plausible within a frozen holding period. The candidate remains unqualified and the historical losses stand.
3. **Next necessary test:** preregister an isolated *new* simulator contract and a truly future uninspected Bybit data window; enforce source-verified recursive wave degree if the study requires real Elliott labeling, actual next-open and stop-first conservative exits, cost profiles, MAE/MFE, independent fill/P&L reconciliation and no after-the-fact parameter tuning. Do **not** turn this forensic observation into a retrospective "successful backtest."

Receipt: [FROZEN_ENTRY_RISK_QA.json](./FROZEN_ENTRY_RISK_QA.json). Physical output retained at `E:\NEXUS-QA\elliott-v16-frozen-economics-20261015\result.json`.

**Safety and architecture:** Research-only at Laptop2; old market producer and journal frozen; Draft PR #2673; no Strategy Finder promotion, Paper writer change, broker calls, live trades or VPS actions. `Live=false`.
