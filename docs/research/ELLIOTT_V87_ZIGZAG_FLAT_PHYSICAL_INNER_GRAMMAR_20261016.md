# NEXUS Elliott V87 — Zigzag / Flat physical inner-degree grammar, historical research (2026-10-16)

## What was implemented
Additive, read-only observer for the **two** verified V82 three-leg corrective skeletons on physically verified Binance Spot BTCUSDT/ETHUSDT 1m **2024-03-01/02 UTC**. Compare **both** predeclared nested correction hypotheses together, not choose the winner after inspecting history:
- **Zigzag 5-3-5:** five, three, five sequential inner legs, corresponding to strict 1m-width-1 *interior pivot counts* **(4,2,4)** in A/B/C.
- **Flat 3-3-5:** three, three, five inner legs, corresponding to strict 1m-width-1 *interior pivot counts* **(2,2,4)**.

Those counts are **only a fixed-degree skeleton**. They do not alone prove Fibonacci structure, correct wave degree, recursive 5-3-5 subdivision, an executable setup, or profitability. Strict one-minute center is confirmed only after the **right closed minute**; parent 15m and child 3m vertices must be physically source-backed and confirmed before the decision. Every strict primitive between endpoints remains visible, including same-kind extras; competing patterns cannot trim inconvenient pivots.

**Source authentication:** Read each V80 ZIP again with the official checksum bound to source receipts; V82 stored two-day parent+child event witnesses are reloaded, SHA-verified and required to match independently recomputed V82 output exactly, with exact correction endpoint timestamps and same hypothesis-first-seen candle. Dual 1m high+low extrema in a single physical candle cause explicit abstention; incomplete/gapped prefix and premature 1m pivots fail closed; future tail data is never read by as-of evaluator.

**Pattern reference taxonomy:** Elliott Wave International's standard corrective wave definitions; see V78 external-source registry and V81 specialist-site review. These are general theory references only, *not evidence the crypto strategy makes money*. Soft retracement ratios remain **observations, not post-hoc tuning gates**.

## Observed results — fixed one-minute inner width, already-inspected historical data

| Metric | BTCUSDT | ETHUSDT |
|---|---|---|
| Original V82 three-leg correction skeletons | 1 | 1 |
| Physical 1m interior counts in A/B/C | **0, 1, 2** | **3, 2, 2** |
| Strict inner zigzag 5-3-5 skeleton | **NO** | **NO** |
| Strict inner flat 3-3-5 skeleton | **NO** | **NO** |
| Observed B retracement of A | ~31.0% | ~91.0% |
| Final reason | NONALTERNATING_ALL_INNER_PIVOTS_RETAINED | NONALTERNATING_ALL_INNER_PIVOTS_RETAINED |
| Full Zigzag / Flat proof, signal, profit | **NONE** | **NONE** |

**Interpretation:** ETH's B retracement is numerically flat-like, but its actual source-backed 1m primitive sequence does **not** certify the three-three-five internal geometry. B retracement by itself is not proof or an entry. These historical examples do not support relaxing filters to relabel a past move. The very narrow width-1 observer does **not** invalidate every possible Elliott correction family, especially across different wave degrees or bigger windows.

## Data-quality correction discovered in dedicated tests
The previous shared V82 `validate_minutes()` checked `m.low<=0` and high-vs-low **before** confirming finite Decimal values; malformed NaN could raise a raw `decimal.InvalidOperation` instead of deterministic `ValueError`. The V87 synthetic adversarial test exposed it. This PR changes the V82 source validator to demand exact Decimal types, finite bounds first, then positive low / high>=low. **No valid historical candle, 1m wave rule, V52 policy or prior receipt was changed.** Malformed input now fails closed consistently.

## Safety / evidence / limits
- Research-only, independent historical market-source exploration, not the V52 untouched future-score Oct 18–Nov 15 window. Binance reference research only; Bybit remains the *only* eventual Paper/Demo execution exchange. No Live.
- `tests/test_nexus_elliott_v87_correction_witness.py`: **13/13 dedicated tests PASS**, including synthetic physically sampled zigzag and flat skeletons plus adverse malformed source, future pivots, gap, future-tail invariance, extra primitive, dual extrema and wrong direction.
- Full Elliott-focused regression on Laptop2: **634/634 PASS**, `Ran 634 tests ... OK`, native `V87_FULL_EXIT=0`. The PowerShell `NativeCommandError` wrapper on unittest stderr is not a Python assertion failure at exit zero.
- Full source-bound result: `docs/evidence/elliott-v87-correction-witness-20261016/V87_CORRECTION_AUDIT.json`. The full V80 market ZIPs remain solely on Laptop2.
- Original V80/V82 source hashes remain preserved; new output is SHA-256 tracked separately. The inspected samples are **not out-of-sample evidence**. No trading code, paper journal, Laptop1 Demo, VPS or external exchange was touched.
- **Next research gate:** independently plan a *previously untouched* sample (more than two days), preregister immutable pattern/degree definitions and rejected cases **before** opening it; then inspect structural coverage and prospective, cost-inclusive results without fitting on old BTC/ETH observations. Do not promote to Demo until source, timestamp, fill and net P/L gates pass.
