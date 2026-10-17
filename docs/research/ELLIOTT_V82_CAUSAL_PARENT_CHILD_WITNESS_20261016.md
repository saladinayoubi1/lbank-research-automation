# NEXUS Elliott V82 — Causal parent/child wave-skeleton observer (2026-10-16)

## Objective and source lineage
Implement the bounded **P0 first increment** proposed in V81: objectively enumerate source-backed parent (15m) and child (3m) extrema, map each pivot price to a **unique strict 1m extrema**, and report incomplete competing *skeleton* hypotheses at the earliest candle-based right-hand confirmation. **This is NOT a recursive 5-3-5-3-5 Elliott classifier, not an Elliott impulse/correction proof, and NOT a trading model.**

**Original reference rationale:** EWI motive/corrective wave descriptions, nested wave degrees and TradingView pivot retrospective-display caveats, cited with original URLs in `ELLIOTT_V81_SPECIALIST_SITE_METHOD_GAP_REVIEW_20261016.md`. No third-party strategy source code was imported.

- Immutable observed data: **Binance Spot BTCUSDT and ETHUSDT official 1-minute OHLC** on **March 1–2, 2024 UTC**, as received and checked under V80 on Laptop2.
- V80 physical source integrity receipt: `docs/evidence/elliott-v80-binance-source-20261016/V80_OFFICIAL_BINANCE_SOURCE_QA.json`; all four ZIPs previously checked against official `.CHECKSUM` SHA256. V82 independently rereads and rehashes ZIPs and the CSV members against that bound receipt.
- V82 result receipt: `docs/evidence/elliott-v82-causal-degree-20261016/V82_RESULT.json`; full exhaustive event-level proof traces are **retained on Laptop2**, not uploaded here: `E:\NEXUS-QA\elliott-v82-causal-degree-observer-20261016\V82_{BTCUSDT,ETHUSDT}_CAUSAL_WITNESSES.json`. Each trace file SHA256 is recorded in the committed summary.
- Source receipt/download timestamp is **2026-10-16 UTC** (see V80 source metadata). V82 `hypothesis_first_seen_ms` is the **earliest counterfactual completed-candle timestamp given full historical data**, NOT the time anyone actually observed or traded a forecast in 2024. No historical hindsight P/L is credited.

## Fixed causal semantics (read-only)
1. Start from verified, gapless 1m UTC OHLC, enforce complete parent 15m decision boundary and ignore any added future bars when evaluating a fixed decision.
2. For parent, use **strict 15m width=3** local high/low; for child, **strict 3m width=1** local high/low. Never compress or selectively drop same-kind pivots to force five legs.
3. For any detected coarse extremum require **unique exact source 1m center** and strict physical **1m width=3** extremum. Unproved/coincident coarse highs/lows are explicitly counted as rejected.
4. The availability time is the **later** of the right-neighbor coarse-bar close and the right-neighbor 1m confirmation close. No pivot from the currently forming bar is considered known.
5. Consecutive parent extrema define exploratory leg intervals; enumerate **all** source-backed child primitives between parent centers that were observable no later than the right parent's confirmation. A sequence with precisely 4 alternating internal extrema is only a **five-leg skeleton**, while precisely 2 is only a **three-leg skeleton**; the rest are explicitly unresolved. Geometry, degree recursion, hard impulse rules, zigzag 5-3-5 / flat 3-3-5 / triangle 3-3-3-3-3 and economic fitness are unproven.
6. A skeleton **cannot emit entry_signal, paper_eligible, live_enabled, or P/L**, and never overrides original V52 frozen evaluation or the existing Bybit-only Demo safety gate.

## Historical exploratory results: two days per pair (not independent prospective scoring)

| Declared observation | BTCUSDT | ETHUSDT |
|---|---:|---:|
| 1m source candles | 2,880 | 2,880 |
| Parent 15m+1m strict witnesses | 33 | 37 |
| Child 3m+1m strict witnesses | 334 | 352 |
| Consecutive parent intervals | 32 | 36 |
| Five-leg **skeleton only** | 1 | 1 |
| Three-leg **skeleton only** | 1 | 1 |
| Unresolved parent intervals | 30 | 34 |
| Real Elliott completion proof, demo trades, P/L | **NONE** | **NONE** |

**No claim of profitability or signal improvement.** Many intervals contain a non-alternating unsuppressed primitive stream; if old engines would have removed these to create nicer patterns, this observer refuses the relabel. Results are **exploratory** on already available historical days, cannot be used to optimize prospective V52 rules. These two days are too short for out-of-sample economic evaluation.

## QA, limitations and next gate
Dedicated synthetic tests verify temporal cutoffs, source-minute continuity, unique center, no future-tail effect, 1m physical confirmation, exact child-count alternatives, abstention, and preservation of extra pivots. Full Elliott-focused regression remains separately required. The source is **Binance, not Bybit**; never equate wick, liquidity or execution fills across venues.

Next additive step: on an independently specified future or previously untouched development *source window*, require full motive/corrective subwave geometry and multiple degree witnesses, preserve ambiguity (no winner-picking), and compare structural rejection counts versus frozen reviewer. Full recursive count, prospective net expectancy and Demo admission remain **open**; do not merge Draft PR #2673 without user authorization. Laptop1 Demo, VPS, V52 and all trading pathways untouched.
