# NEXUS Strategy Finder — first bounded declarative executable intake (18 Oct 2026)

## Problem actually observed

The Strategy Finder ecosystem documents 15 research families, 29 reviewed *design descriptions*, a separate novelty ledger, and a previously executed/terminal factory frontier; **these are not interchangeable**. Until now a new catalog design with only natural-language entry/context/exit/risk tokens could not be executed by the existing `nexus_mechanism_factory.factory_signal` grammar without adding new hard-coded code or changing the existing reviewed fixed/auto-generated frontier. The terminal stage must stay stopped if exactly reviewed fingerprints are exhausted, rather than restarting the same experiments.

The financial 500 USDT one-book gate is now source-verified and merged to `main` in #2715 / #2716. It cannot by itself create a genuinely independent strategy. This new change supplies the **missing strict, gated handoff from a separately reviewed executable DSL contract into the existing 500-USDT account evaluator**. It is a *research intake mechanism*, **not** automatic discovery, arbitrary LLM-generated Python, alpha proof, or permission to trade.

## New files and exact scope

- `scripts/nexus_strategy_finder_executable_intake.py`: read-only, strict executable-contract loader, qualitative duplicate filter, separate allowlist gate and bounded 15m/1h/4h Bybit `factory_signal` → next-open BTC/ETH single-wallet simulator bridge. The original `nexus_mechanism_factory.load_factory_contract` validates the candidate grammar and rejects unknown fields/operations. **No existing fixed or generated mechanism grammar is modified.**
- `research/strategy_finder_executable_intake_allowlist_v1.json`: **zero approved executable contracts** at creation. This is intentional: a new project-data proposal can be syntactically executable but not independently approved for simulation. A future independently reviewed GitHub PR must explicitly pin exact raw candidate file SHA256, its qualitative signature, PR URL, independent legacy semantic review, and source provenance. Declared review fields are necessary, **not sufficient evidence that an outside review actually occurred**; reviewers must substantiate them.
- `research/intake_candidates/factory_prior_day_sweep_peer_resilience_v1.json`: **one completely frozen, unapproved proposed hypothesis**. Unlike V118 breakout and V119 Wave2 support, this is a prior-*completed-UTC-day* downside sweep/reclaim in a completed 4h range with previously completed 1h volatility context and *lagged* cross-pair beta residual plus downside variance profile. A long-only next-open research study might falsify it. It uses already approved causal OHLCV+peer features, no L2, funding, indicators requiring unavailable inputs, subjective Elliott counts, or unobserved same-candle future values.
- `tests/test_nexus_strategy_finder_executable_intake.py`: **16 adversarial tests PASS** on isolated Laptop2 using existing current-main factory+500-shared-gate module snapshots and the new branch proposal/allowlist.

## Why no false novelty or parameter treadmill

A candidate's qualitative comparator strips ID, family label, natural-language hypothesis and scalar-threshold **magnitude** while retaining ordered stages (context vs entry), independent AND predicates, field/op, RHS field-vs-scalar, scalar sign, explicit binary state and RHS scale sign. AND-terms are sorted so permutation is no novelty. All current fixed and generated original factory grammars are compared by this normalization. Same qualitative conjunction with only a threshold/name change => `REJECT_DUPLICATE_EXECUTABLE_TOPOLOGY`; reuse of original executable ID => `REJECT_DUPLICATE_EXECUTABLE_ID`, even if the conditions changed.

This filter is **heuristic and intentionally conservative**. It cannot prove global semantic novelty against original non-declarative Python strategy families, previous Elliott/Butterfly research or the market literature. The first proposed price-action sweep **may overlap** existing generic failed-range-break-reversal patterns. Therefore no candidate has been independently approved, no old ledger/fingerprint changed, and nothing was dispatched.

## Original first machine-evaluated proposal

- Candidate ID: `factory_prior_day_sweep_peer_resilience`
- Candidate file raw SHA256: `ad20bb4b3d18da4b601793c6bdccdf42623187803df7389ffb2b6da3e75be92d`
- Normalized qualitative signature: `e83d180e07abb446a1ad8ab4452e3e8375e6479d3fe1e14783689d5109a42fa3`
- Full strict factory contract digest: `d17c0277801481acbc995f6467a0105e20d6e523d6859467041cf0b06b945295`
- Existing factory fixed/generated duplicate signatures: **0**; this is NOT independent cross-family semantic evidence.
- **Status:** `REVIEW_REQUIRED_NO_SEPARATE_APPROVAL`; approved research backtests **0**, exchange/Paper/Demo orders **0**, profitability unknown; `paper_eligible=false`, `live_enabled=false`, `automatic_dispatch=false`.

Fixed proposed signal protocol (no retrospective threshold changes): within an already completed higher-timeframe range, positive lagged BTC/ETH beta residual, observed lagged downside variance ratio over 0.5; a completed 15-minute bar physically breaks the *previous fully closed UTC day's low* but closes back above it, closes bullish with close-location >=0.6 and volume >= its lagged 20-bar baseline. The earliest permitted hypothetical entry is the **next** 15m open. Original shared cash research risk (if later separately reviewed): 500 USDT one cash wallet, max 250 USDT gross long and 2.5 USDT nominal gapless stop loss, 1.5ATR stop, 2R target, 64-bar timeout, two predeclared normal/stress fee-slippage profiles.

This is a **testable proposal**, not a recommendation to trade, not proof this conjunction is novel or profitable. The user's Elliott wave prospective V117 remains separately frozen and must not be contaminated.

## Integrity, fail-closed behavior and operational limitations

- Executable candidate must be a single fixed `research/intake_candidates/*.json` inside the repository, strictly original factory grammar, with one candidate per review. No absolute paths, source Python, dynamic imports, script expansion, unauthorized input fields or unreviewed custom execution.
- Approvals are matched on `candidate_path`, `candidate_id`, raw candidate SHA256 and qualitative signature. A stale approval after *any* file change fails closed, as do invalid authority values, missing independent review/source fields, duplicate approval keys, unsupported condition and mutable candidate identity.
- Byte-level SHA256 of all six original Bybit Spot 15m/1h/4h parquet blobs, with verified timestamps and physical OHLC, is checked **before any market features**. Hypothetical evaluation windows are UTC-aligned, 25+ days warmup, 30+ days scored and <=150 days total, to avoid exhausting Laptop2's 4GB RAM.
- If separately reviewed in the future, the exact original factory signal on completed 15m bars flows into the already tested 500-USDT shared BTC/ETH cash simulator with next-open entry, hard stop-first ambiguous-bar priority, worse stop-gap fill, fee/slippage stress and six 60/20/20 research split reports. This remains **preinspected historical diagnostic**, no future independent OOS.
- Explicit allowlist is empty now, so **none** of the new proposed conditions can execute or trigger synthetic Paper, owner Demo or live exchange orders. The original deployed main discovery controller, exhaustive ledger, scheduler, old candidate configuration files and research jobs are unchanged. Installed Laptop1 Owner product, Bybit Demo, Paper journals, credentials and runner are untouched.
- Original prior results remain real negative evidence: Elliott V118 four physical losses; Elliott V119 77 mixed results with total negative; `structural_pullback` source-verified Q1 2025 shared-cash negative on all three independent historical portions. **Do not retune any of them against their already inspected outcomes.**

## Tests / acceptance

Isolated Laptop2 **16/16 tests PASS**, native exit 0, source versions tied to exact GitHub branch and original current-main dependencies. Explicit assertions: original allowlist empty; candidate blocked despite executable grammar; exact standalone permit can only enable research mode in synthetic in-memory tests; threshold tuning, reorder, new family/hypothesis rename cannot defeat structural filter; old ID reuse prohibited; stale raw hash rejected; duplicate predicates and unapproved field code injection fail closed; PR authority spoof, outside-repo paths, and unapproved market-data attempt rejected; the actual proposed JSON is strict grammar-valid but unapproved.

An additional synthetic entry witness executed the actual original `factory_signal` interpreter for the proposed DSL on two physically possible closed-candle states: a prior-day-low sweep/reclaim produced `True`, while a close below the prior-day low produced `False`. This demonstrates **testability**, not market alpha or independent semantic novelty. The committed real allowlist stays empty.

Next genuinely substantive gate, before **any** first market replay of this new proposal: independently review against the old failed-range family to decide whether the proposed *previous complete day low + peer beta residual* is a materially different causal mechanism, and verify original Bybit spot data & cost assumptions on a separately accountable QA lane. If actual approval is earned, add a distinct reviewed GitHub PR allowlist record before simulation; if this is an alias, **reject the proposal without backtesting**, not a new string ID. Live remains disabled regardless.
