# Elliott V50–V51 — fixed 3-minute degree proposal and causal prefix replay

**Research date:** 2026-10-16  
**Device:** Laptop2 `DESKTOP-F4SA4VL`  
**PR:** #2673, **Draft**. All data in this study are previously inspected historical Bybit public Spot trades, **not a fresh prospective holdout**.

## V50: non-retuned child degree proposal

The old V49 fixed-child method counted every strict 1-minute pivot and rejected an ETH parent-wave candidate because six internal extrema occurred in the first parent leg rather than the four needed by the limited V40 5-3-5-3-5/ABC checker. V50 tests a different **structurally predetermined** degree hypothesis: child bars use **15-minute parent timeframe divided by five = 3-minute bars**, not an empirically optimized profitable threshold. It does **not** retroactively remove pivots to fit a result.

`research/elliott_v50_fixed_degree/propose_degree_v50.py` processes UTC-complete 1-minute bars and computes strict width-one 3-minute high/low candidates from fixed UTC-aligned buckets, requiring the right-hand 3-minute candle to have closed. Each coarse pivot must resolve unambiguously to a strict width-three physical 1-minute extremum and match its source price. Missing, naive-time, ambiguous, duplicate/off-grid, malformed OHLC, future/incomplete and non-source-bound parent inputs are rejected. Only consecutive same-kind internal candidates can be replaced by their more extreme point, per the predeclared rule. Complete V40 parent and all eight 5/3/5/3/5 + 5/3/5 child segment geometry are required before reporting a **bounded one-child-degree** proof; even that proof emits **no trading signal, no Paper eligibility, and no recursive-complete claim**.

The isolated synthetic regression suite includes 14 tests (including a complete bounded positive witness, negative corrupt/future tests, timezone correctness and prefix invariance): **14/14 PASS**.

### Real-source result

Input: V48's uniquely source-bound nine-parent ETHUSDT candidate 2026-10-10 from BTC/ETH October 8–12 1-minute source V45, independently audited in V46. The V50 fixed 3-minute selector found the same first-leg cardinality rejection:

- `DEGREE_COUNT_MISMATCH_LEG_0:required_4_interior_got_6`
- For the full five-day ETH 1-minute source, 939 verified 3-minute candidate extrema and 88 ambiguous/unverified coarse extrema were recorded; this is a **diagnostic count**, not a trade count.
- No bounded child-degree witness was admitted for the fixed ETH parent candidate; no BTC parent candidate existed in this source window.

This rule was formulated **after inspection of historical V49 outcomes**. Its successful synthetic tests do not validate the choice of timeframe and do not turn the historical ETH case into prospective evidence. Future economic studies require independent preregistration and unseen data.

## V51: explicit replay starting only after the last 15-minute parent confirmation

A separate replay script independently verified the final ETH parent 15-minute width-three pivot and exact first admissible decision close **2026-10-10 23:45 UTC**. It reconstructed physical, hash-pinned as-of prefixes using V42 at five decision times from that first close through 2026-10-13 00:00 UTC. At each point, it ran both the original V49 1-minute and new V50 3-minute degree proposals.

All five decisions generated exactly the **same fail-closed first-leg reasons and six observed first-leg internal extrema**, independent of additional future bars. No late market data can change the audited conclusion for this fixed candidate under these algorithms in the tested replay window. This is **not** a proof that the algorithms are generally causal for every possible input.

### Reproduced statuses

| Gate | Result for all 5 historical replay decisions |
|---|---|
| Parent decision after independently confirmed 15m pivot | PASS |
| Historical 1m source pinned by SHA and sliced to exact decision time | PASS |
| V49 1m fixed degree cardinality | FAIL, 6 observed vs 4 required |
| V50 3m fixed degree cardinality | FAIL, 6 observed vs 4 required |
| Signal/order/Paper promotion | NONE |
| New realized P/L | null |

## Local machine evidence, SHA-256

Root `E:\NEXUS-QA\` (files preserved on Laptop2, **not uploaded** as binary GitHub artifacts):

- `elliott-v50-fixed-3min-degree-20261016/V50_REAL_DEGREE_QA.json` — `b5feb5cd2a94c1b845241f114146f668af2000bc9cbbb0726c8ba3ae9ce36f51`
- `elliott-v51-asof-replay-20261016/REAL_PREFIX_INVARIANCE.json` — `01413afd22f85298b615399e0f79359fb26565ee45b4b8f02320fcb3a83f9292`

## Remaining scientific gap and next admissible work

A genuine Elliott degree-assignment method remains unproven. A valid next experiment must **pre-register a degree hierarchy before market observations**, verify against independently sourced, complete lower-timeframe bars with causal parent and child confirmation, and report nonadmission faithfully. Do not optimize pivot-selection on the known historical loss trace or market outcomes. Before any separate Demo decision, require genuinely unseen post-signal quote/fill source, conservative costs, stop-first/gap ordering, and independent P/L audit.

**Safe state:** `research_only=true`, `live_enabled=false`, `paper_eligible=false`, `entry_signal=false`, `recursive_complete=false`, `observed_pnl=null`. Keep PR Draft, Laptop1 Paper and VPS untouched.
