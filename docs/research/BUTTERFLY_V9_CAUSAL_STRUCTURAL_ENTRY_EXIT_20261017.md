# NEXUS — Butterfly V9 structural exit research protocol (17 October 2026)

## Research-only status and existing evidence

This is an **execution-protocol design and synthetic contract**, NOT a new backtest and NOT economic qualification. It preserves the rejected V8 source result (independent source-bound cost QA in merged PR #2711) and all frozen Elliott V117 November 2026 evidence. No source dates or historic returns were used to choose V9 exit coefficients. V9 is **not** automatically eligible for Demo/Paper. Historical novelty and future performance are unknown.

### Engineering gap isolated

The previous causal Butterfly V8 detects a geometrically valid XABCD pivot configuration, but the generic composite backtest attaches a fixed **1.5×ATR stop** and **2R take-profit** at the next open. Those generic exits are not structurally tied to the Butterfly reversal zone (D) or CD leg. Its lagged event feature exposed confirmation/D/rebound but not a complete structural exit tuple. It also cannot make hypothetical next-open admittance decisions at the preceding closed-bar time.

[HarmonicTrader's official Butterfly pattern specification](https://harmonictrader.com/harmonic-patterns/butterfly-pattern/) treats the 0.786 XA B retracement, around 1.27 XA D projection and the Potential Reversal Zone (PRZ) as defining geometry. Its [advanced stop-loss discussion](https://harmonictrader.com/wp-content/uploads/2020/06/HarmonicTradingV3Carney.pdf) describes an invalidation reference beyond 1.414 XA for a bullish Butterfly. These are **reference conventions, not published Bybit profitability statistics**. The new first target at 38.2% of the confirmed C→D decline is a *preregistered research choice*, not a claimed ideal source rule or winner.

### Frozen V9 hypothesis / precise capital and timing

- Reuse **the identical immutable V8 causal pattern grammar**: strictly confirmed X low, A high, B low, C high, D low, right-confirmation 3 completed 15m bars, one further completed confirmation bar, maximum 192-bar X→D span, original Fibonacci ranges.
- Signal decision is after the **very first** completed 15m bar following D's causal right-confirmation; never revise past signal state, never use pivot center as the entry timestamp. Complete H1 volatility context must be from the most recent **closed** hourly bar on a strictly UTC-hour-anchored 15m grid. No current still-open H1 state allowed. Confirm closed reversal body, close > previous close, and same original V8 price rebound trigger D+0.10×XA.
- Only after creating a signed immutable close-time intent may a **different pure function** observe the immediately next 15m candle OPEN. No same-bar "repaint" or future-candle quote may retroactively create the original decision.
- For bullish X–A–B–C–D, frozen hypothetical structural stop price = **A − 1.414×(A−X)** (beyond D); first hypothetical target = **D + 0.382×(C−D)**. Reject when prices or geometry fail; no ATR stop/2R substitution and no post-hoc tweaking.
- Reject next-open fill if price already below structure stop, at/beyond first structural target, or cost-adjusted target proceeds are not positive. No limit orders or fill claims at D, wave extrema or signal close.
- **500 USDT isolated hypothetical cash**, ≤10% gross allocation, ≤0.5% *nominal gapless* stop-risk budget, one research long/no short/no leverage. Per-side fee/slippage conservative 10/5 bps; stress 25/15 bps. Estimated gapless loss is **not** a guaranteed realized stop fill if the real market gaps past it. No simultaneous position portfolio admission has been implemented.
- A source-bound future test still needs independently attested Bybit/Spot full OHLCV bars, actual next-open fill, first stop/target intrabar touch (same bar: stop first), worse opening gap-through price, final time exit, monthly P/L, validated single-account cash, previously unseen forward sample, Independent QA and anti-multiple-testing guard. **Those are NOT supplied by this V9 module**.

### Exact scope

Source: `research/butterfly_v9_structure_exit/plan_v9.py`; QA: `tests/test_nexus_butterfly_v9_structural_execution.py`; rulebook: `docs/evidence/butterfly-v9-structural-prz-20261017/V9_PREREGISTERED_STRUCTURAL_STOP_TARGET.json` (`contract_digest=813581410e3fa6c1f66ddb2ed42a7f4a80b28101756b41e9996b8c5480a58b85`).

The new code exposes only `close_time_plan`, `hypothetical_next_open` and `frozen_rulebook`. No live broker methods, exchange credentials, network requests, timestamps from future archives, strategy auto-dispatch, entry orders, Demo subscriptions or runtime integration.

Laptop2 isolated synthetic QA: **23 tests passed**, including stale D confirmation, causal H1 boundary, later OPEN only, start-of-gap structural rejection, cost stress, frozen stop/target and immutable prior decisions. **Zero physical forward market records and zero economic P/L results**. The already rejected Butterfly V8 historical results must not be replayed and reselected to make this design appear profitable.

### Scientific decision

**DESIGN_UNQUALIFIED_REQUIRES_FUTURE_INDEPENDENT_OBSERVATION**. Preserve old V8 rejection, freeze V9 structure before any future economic evaluation, and do not change existing V117 planned November 16–30 2026 original prospective Bybit arms. Without externally observed future results and independently verified account P/L, keep all Paper/Demo and Live authority disabled.
