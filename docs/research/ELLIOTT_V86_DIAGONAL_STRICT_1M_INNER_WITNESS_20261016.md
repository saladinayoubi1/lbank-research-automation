# NEXUS Elliott V86 — strict 1m inner-wave witness / diagonal abstention (2026-10-16)

## Purpose and method
Read-only follow-up to V85: verify whether the *already inspected* historical, five-leg BTC/ETH skeletons admit a full fixed-degree **three-leg inner skeleton in each of their five component legs** without selectively deleting primitive 1m pivots. This is a **narrow falsification observer** for the V81/V85 hypothesis, **not** a recursive 3-3-3-3-3 Elliott classifier or a test of all leading/ending diagonals.

Method fixed for this exploratory implementation: physical Binance Spot **BTCUSDT and ETHUSDT, March 1–2 2024 UTC**, raw 1m OHLC from four prior V80 verified official ZIP+CHECKSUM files; each strict local extrema with left/right **one** adjacent 1m candle must be confirmed by the right candle close. Fully preserve every confirmed primitive, no same-kind collapse, hindsight grouping, edited OHLC, threshold fitting or cherry-picked subsequences. Count all such inner extrema strictly between consecutive V83 source-backed vertices; a simple three-leg skeleton under this **fixed-width observer** requires exactly two alternating inner extrema. Even when those two exist, **A-B-C geometry, full subdegree hierarchy, leading/ending location and wedge geometry remain unproven**.

Dual-direction local extrema in the **same 1m candle** cannot be reliably ordered from OHLC and are timestamped; any such ambiguity inside an evaluated leg vetoes the simple three-leg skeleton. Future and malformed data after the decision time never participate in the point-in-time evaluation; missing or invalid within-prefix data fail closed.

## Source and causal recheck
- `V80_OFFICIAL_BINANCE_SOURCE_QA.json` establishes daily official source ZIP/checksum and 1m continuity. Current V86 independently rehashes each ZIP and member via the V82 loader.
- V83 physical impulse path and V85 diagonal necessary-veto outputs are **recomputed** and required to match their original immutable JSON data exactly. Historical V85 rejection is *not* overridden.
- The archived complete result and all inner event observations are in `docs/evidence/elliott-v86-diagonal-inner-20261016/V86_INNER_CENSUS.json`; original source ZIP and local test logs remain outside GitHub on Laptop2.
- A retrospective historical **causal candle-close timestamp** is not proof that anyone made a forecast in 2024. This data was obtained in 2026 and is not the V52 prospective held-out period.

## Actual historical inspection — fixed 1m width-1 observer

| Observation | BTCUSDT | ETHUSDT |
|---|---|---|
| V85 five-leg parent candidate | hard-rejected (third motive leg shortest) | preliminary geometry only, not proven |
| Strict 1m interior pivot counts for legs 1–5 | **5, 2, 3, 0, 0** | **7, 2, 3, 0, 0** |
| Components with exactly two alternating pivots (skeleton only) | 1 of 5 | 1 of 5 |
| All five inner three-leg skeletons established | **NO** | **NO** |
| Diagonal fully validated, forecast, order, new P/L | **none** | **none** |

Even ETH fails this chosen *one-minute fixed-degree* inner witness. **This is not a universal Elliott diagonal invalidation**: smaller-scale market noise may require a predeclared degree definition beyond 1m; none may be post-hoc selected on these already inspected ETH bars. A single acceptable three-leg skeleton is only a preliminary shape, not A-B-C.

Global OHLC ambiguous double extrema were recorded separately (**BTC 21, ETH 12** up to relevant as-of bounds) instead of silently manufacturing a pivot order; affected-leg ambiguity and all reasons are provided in the full evidence JSON.

## QA and controls
- `tests/test_nexus_elliott_v86_inner_witness.py`: dedicated **14/14 PASS** (as-of future-tail invariance, missing/gapped prefix, strict right-hand confirmation, dual-extrema abstention, extra primitive retained, alternation, bogus future confirmation, no trading assertion).
- Full repository Elliott-focused regression: **621/621 tests PASS**, Python `Ran 621 tests ... OK`, native PowerShell execution reported `V86_FULL_EXIT=0`. (The red PowerShell stderr wrapper on `unittest -q` is not a Python failure.) No prospective profitability can be inferred from any of these tests.
- Research observer is additive under `research/elliott_v86_diagonal_inner_witness`, not a producer, strategy, live endpoint or Demo executor. V52 future-scoring protocol and the Laptop1 install are untouched. Bybit remains Demo/Paper only if future prospective performance and source gates permit promotion.
- **Next isolated experiment:** predefine and test true zigzag 5-3-5 / flat 3-3-5 correction-family grammar with physical subwave proof, preserving unresolved/ambiguous outcomes. No PR #2673 merge without explicit authorization.
