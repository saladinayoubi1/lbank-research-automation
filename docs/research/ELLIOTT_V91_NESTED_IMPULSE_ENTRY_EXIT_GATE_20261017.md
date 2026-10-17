# NEXUS Elliott V91 — nested 5-3-5-3-5 structural audit and entry/exit deny gate

**Scope:** additive read-only research. The newly audited historical BTC/ETH July 1–14, 2024 source has **already been evaluated** in locked V90. No adjustment of V88/V90 frozen thresholds, source dates, pivot-selection rules or V52 prospective protocol was made. No Bybit order, Laptop1 Demo change, VPS or live execution.

## What V91 proves and does not prove

V83 checks the **outer** necessary geometry of a *conventional non-diagonal impulse* for six source-bound outer pivot endpoints. This is not a full recursive Elliott wave count. V91 asks one additional, narrow fixed-degree question: do all **five** constituent impulse legs have all requisite **1m width-1**, strictly right-confirmed interior extrema under the predeclared **5-3-5-3-5** leg anatomy? Expected untrimmed interior counts are **(4,2,4,2,4)**, with exact alternating polarities, source-time order, and no ambiguous high+low same-candle event within any leg.

The V91 evaluator consumes only V90's **Git-committed SHA-256-bound original per-candidate observations**, which already attest official V89 ZIP+CHECKSUM source and V82–V87 physical 1m/OHLC pivot replay. It verifies the exact V90 immutable Git blob and ancestor commit, all outer and inner confirmation instants, nested primitive count integrity, order and kind. No extra pivot deletion is allowed. A **successful** nested skeleton would still be only a *limited fixed-degree witness*: wave placement, alternative counts, multilevel recursion, wave-specific geometry and prospective trading setup are **NOT** established here.

## V91 actual result on the frozen July V90 universe

| Metric | BTCUSDT | ETHUSDT |
|---|---:|---:|
| Five-leg motive skeletons from V90 | **6** | **2** |
| Rejected by ordinary outer impulse geometry | 5 | 2 |
| Ordinary outer geometry passed but has ambiguous inner OHLC source order | **1** | **0** |
| Fully established nested fixed-degree 5-3-5-3-5 skeleton | **0** | **0** |
| Certified complete recursive Elliott entry setup | **0** | **0** |
| New Demo orders / backtested fills / P&L | **0 / 0 / not evaluated** | **0 / 0 / not evaluated** |

The one historically appealing BTC outer geometry pass has **observed strict 1m interior counts (2,0,4,3,3)** and **one ambiguous dual-direction local-extremum bar** inside its inspected candidate. Therefore it cannot be treated as a 5-3-5-3-5 impulse under this fixed-degree witness definition. This is not proof that all Elliott patterns or all possible degrees are impossible; it is a precise rejection of this *specific* observed candidate under the preregistered rule set.

## Post-confirmation entry and exit contract — fail closed

A completed-pivot timestamp and a retrospective pivot-center timestamp are **different**. The first hypothetical 1m bar at which an algorithm could possibly act is the minute that begins **at the confirmed decision instant**, not at the earlier pivot center. Even that is **not an entry signal**; any practical order needs additional independently tested market data and strategy logic.

The research-only `research_entry_exit_gate()` returns `order_admission=DENY` for **every** input (even a synthetic structurally clean 5-3-5-3-5 skeleton). It explicitly refuses orders until evidence exists for a recursive source-backed wave count, correct wave degree/pattern position, **predeclared post-confirmation entry trigger**, protective invalidation/stop, profit/timeout exit rules, realistic fee/spread/slippage, and Bybit Demo fill/SL/TP sequence semantics. Consequently entry price, protective stop, profit target, timeout, quantity and net P/L remain `null` rather than invented.

**Critical scope:** This gate is **not wired to the production/demo order path**. It prevents *this research module* from asserting eligibility; it is not proof that every pre-existing runner is guarded. No deployment or production setting was changed.

## Immutable evidence and next gate

- Source: original SHA-attested V90 report committed in `cda4423b47926ea0b0b05ab6e38b5aa8e73c37e4` with exact SHA-256 `1db892fcfe75699ded97151501e538d04c2fd8ae4084765c9e1cd4aa9fd4683a`.
- New V91 evidence: `docs/evidence/elliott-v91-nested-impulse-gate-20261017/V91_NESTED_ENTRY_EXIT_GATE.json`, retaining all eight candidate outcomes and explicit missing execution requirements. Raw original ZIP source and full regression logs remain only on Laptop2.
- Next research stage: design and preregister **fully recursive, executable** entry/exit hypotheses, microstructure cost/fill contracts and rejection states **before opening another uninspected sample**. Testing infrastructure reliability alone does not imply positive trade expectancy.
- Bybit DEMO/PAPER only, Live Trading remains disabled, no position is created. V52 Oct 18–Nov 15 prospective scoring untouched. PR #2673 remains Draft/unmerged.

## Actual QA results

- Dedicated tests `tests/test_nexus_elliott_v91_nested_gate.py`: **16/16 PASS**, `V91_DEDICATED_EXIT=0`, including physically ordered synthetic bullish/bearish 5-3-5-3-5 skeleton cases (still nontradeable), missing/extra points, dual OHLC ambiguity, no future pivot, no false entry flag, and full eight-case locked historical census.
- Complete Elliott regression: **695/695 PASS**, `Ran 695 tests in 49.817s`, `OK`, native `V91_FULL_EXIT=0`. Local regression text SHA-256: `d621a387a4ca18c3bdfe33957cbddce6ee7544fc434c0fc07d8415ac808f67c8`.
- Evidence JSON SHA-256: `d4401a5606dee6a0842d1ee3752375dc95de732b9189eb3e65983640ec1715c0`; one copy is Git-tracked and one immutable local snapshot exists on Laptop2.
- **No CI pass for this future commit is claimed until GitHub specifically confirms its workflow results.**
