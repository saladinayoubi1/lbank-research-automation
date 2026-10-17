# NEXUS Elliott V101 — prospective preregistered non-diagonal Impulse *necessary* structural screen

## Decision and provenance

**V101 has no market evaluation or real-world P/L.** It freezes, before looking at future data, one narrow falsifiable family hypothesis: a non-diagonal, non-truncated five-leg Impulse-like structure with physically confirmed predecessor context and source-matched fine/coarse events. The frozen rulebook is the committed JSON `docs/evidence/elliott-v101-preregistered-grammar-20261017/V101_PREREGISTRATION.json` with SHA256 **`735d942cdcbf802f6079e5435473e91b7d5b597831087ab4a7439ab04984e221`**. Re-running the freezer verifies byte-for-byte identity; modifications fail closed.

V99 introduced two *independent* causal close-only directional-change scales; V100 accounted for all fine events against all coarse windows without retrospective pivot deletion. **Neither is an authenticated Elliott market degree**, and matching two scales on the same underlying price data is not independent corroboration. V101's single-family rulebook does not promote V100's source-matched pivots into proof of an Elliott wave or trading edge.

## Untouched prospective research window — strictly outside frozen V52

- **Future UTC interval:** **2026-11-16 00:00:00 inclusive** through **2026-11-30 00:00:00 exclusive**, a full **14 days**. Do not touch the frozen V52 Oct 18–Nov 15, 2026 protocol.
- **Market source required for any later V102 evaluation:** Bybit **public Spot** one-minute closed OHLC, BTCUSDT and ETHUSDT (fixed universe, expected 20,160 complete 1m closes per pair). **The data have not yet occurred as of V101's creation date and have not been requested or inspected.** An independent, verifiable Bybit source / checksum / completeness / timestamp receipt and availability assessment must precede any market outcome claim. Missing or region-blocked Bybit source means no result, not substitution with a different exchange.
- Reuse the already frozen V99 60 prior closed one-minute absolute return median, multipliers **3** and **8** and floor 0.03% of previous closed price. Do not tune against V88–V100's repeatedly inspected July 2024 observations.
- Do not evaluate a truncated subset: the future-only evaluator rejects missing, out-of-window or partially closed market data. No alternative timeframes or symbols may be added post hoc.

## Frozen V101 candidate enumeration

For every *consecutive* window of **seven** independently confirmed scale-8 coarse pivots, with no skipping, the first is a **previously confirmed predecessor context witness** (not proof of pattern position) and the next six form a five-leg Impulse hypothesis. Every original scale-3 fine pivot remains accounted for, including matching boundary events and all interior swings.

The *restricted necessary* nested 5-3-5-3-5 shape requires exact interior scale-3 pivot counts **4, 2, 4, 2, 4**, **without trimming extra pivots**. Each of the six candidate coarse boundaries must independently match a fine swing with the same historical center, direction and close price, confirmed no later than the corresponding coarse boundary. A subwave confirmed after the right coarse boundary's confirmation must be refused; earlier candidate windows may use **only** events already closed at their own original decision instant. V100 also enforces monotonic source-minute index, causal timestamp, strict alternating direction, and a single source epoch.

Conventional **non-diagonal, non-truncated** five-leg outer geometry must pass:
- First directed leg positive; Wave 2 must not cross the start of Wave 1.
- Wave 3 extends beyond the end of Wave 1, and cannot be the shortest positive motive leg.
- Wave 4 must not overlap the Wave 1 price domain.
- Wave 5 must extend beyond Wave 3.

Every sliding candidate is reported, whether it passes or fails. No after-the-fact best count, alternative family, retracement optimization, PnL winner selection, intrabar high-before-low inference, or early center-time entry. A positive necessary skeleton **still lacks** full nested physical Elliott grammar, independently proven degree/pattern position, wave-end execution cost validation and calibrated false-positive rates. `full_elliott_market_wave_proven=False`, `pattern_position_proven=False`, `paper_eligible=False`, `entry_signal=False`, `live_enabled=False` unconditionally.

## Software gates and safety

Module: `research/elliott_v101_preregistered_grammar/grammar_v101.py`.
Tests: `tests/test_nexus_elliott_v101_preregistered_grammar.py`.

The V101 tests use **synthetic events exclusively**, including an intentionally passing *structural* example that is categorically *not* a real market Elliott pattern or trade. Negative tests cover missing predecessor, wave-4 overlap, missing two inconvenient fine swings, boundary price mismatch, future-unavailable confirmation, nonaligned timestamps, event index/source-time mismatch, deterministic sealed manifest and rejection of old or partial source as new future validation. V101 did not run the future evaluator against **any market observations**.

No Bybit API credentials or orders, no modification to Laptop1 Demo, V52, runner, VPS or paper journal, no Live Trading and no PR merge. The existing Draft PR #2673 remains the research boundary.

## Interpretation and next independently gated step

V101 is **preregistration and unit validation only**, not strategy success. Future V102+ must independently acquire and authenticate the complete fixed Bybit Spot 1m data *after the future window finishes*, seal raw-source receipts, execute all frozen candidate decisions at their original confirmation timestamps, analyze all failures and abstentions, and apply conservative Bybit-compatible fees, spreads, slippage, stop-before-target logic only **after** independent waveform and pattern-position proof. No position may be created from V101 screen alone.

## Verified freeze and QA — 2026-10-17

- **V101 frozen rulebook** was generated *without fetching a single future source row or evaluating a single real candidate*. Native `V101_FREEZE_EXIT=0`. Sealed SHA256: `735d942cdcbf802f6079e5435473e91b7d5b597831087ab4a7439ab04984e221`.
- **16/16 V101 tests PASS**, native `V101_TEST_EXIT=0`; this includes a positive *synthetic structural* fixture and adversarial tampering/retrospective dataset rejection. No live or paper orders can be generated.
- **863/863 full Elliott tests PASS** locally on Laptop2, `Ran 863 tests in 51.001s`, native `V101_FULL_EXIT=0`. Local test log SHA256 `67d846438a308e455979ad306512973c829ee5145f4c0a6794f428b23ff34878`, at `$env:TEMP\V101_FULL_ELLIOTT_REGRESSION.txt`.
- **V100 predecessor GitHub CI**: `Test`, `Research Evidence Refresh`, `Workflow Permissions Policy` all **success** on original commit `639fc5840340ab9dde762130e35e035abd45d8e7`. V101 remote CI requires independent confirmation after push; do not represent local success as GitHub Windows/macOS/Ubuntu acceptance.
