# Fixed portfolio forward executor and separate numerical QA

The existing raw-source route now has an executable consumer for the original
fixed portfolio engine and a separate signal/accounting reconstruction. This
maintenance belongs to Strategy Factory, Data Intelligence and verification:
DATA-21, RES-32, VAL-40 and QA-41. The original engine, source contracts,
Manager definition and prior negative studies are unchanged.

The only scoring period remains **[2026-10-19T00:00Z, 2027-01-17T00:00Z)**.
Both execution and financial QA reject an incomplete horizon before any input
receipt, market source or output is opened. The source consumer also checks
the current clock itself. There is no CLI clock override, schedule, network
operation, strategy search or Manager dispatch in this integration.

## Source-to-engine connection

`research/portfolio_v3_forward_executor_v1.json` is canonical-digest locked.
Its code/contract pins include the unchanged engine, fixed candidate handoff,
source freeze, warmup/context preparation, raw-source route and independent
source/financial verifiers. Loaded modules must match the pinned files.

The consumer requires the approved historical `context.json`, digest
`bd3b57243c7ac5c6ed017b8840df77f4d1bec519a1449e964bb3b4e27e6bc3d3`,
and its exact sealed NPZ. It rehashes the six original archive files and loads
the already prepared 8,508-row context; it does not recapture or reaggregate
the completed historical warmup.

Future input requires the separate full-tick Decimal source-QA artifact and
the retained 180 raw files/daily acquisition receipts. The consumer rehashes
every raw day/receipt, checks capture/QA identity and totals, and reconciles
all 540 source-bound OHLCV rows per asset against retained daily receipts.
The join preserves the original 2022-12-01 UTC grid through the full future
end: 9,048 rows per asset. No missing candle is synthesized. Local source
receipts do not claim an exchange signature or external-host attestation.

Only the existing `bybit_portfolio_search_v3.exact_backtest` determines the
producer's fills. Candidate `b4e4a2c33304aec1`, global 42-bar schedule,
30/90/180-day ranking, sizing, original costs and fixed post-hoc DD20
comparison remain unchanged. Original period semantics skip local row zero
and first execute its prior target at row one's open; the bridge preserves
that behavior without importing pre-period holdings. No physical per-lot
SL/TP has been added; that remains an admission limitation.

| Book | Allocation/execution |
|---|---|
| Original dual rotation | Original fixed targets and global review schedule |
| Original plus fixed DD20 | Same targets; closed-bar trigger, next-open exit, permanent halt |
| Passive BTC | Buy once at the original first eligible open, then hold |
| Passive ETH | Buy once at the original first eligible open, then hold |
| Passive 50/50 | Initial equal weights, then drift without rebalancing |
| Cash | No fills |

Each book is evaluated at the three already frozen cost profiles: exactly
18 counterfactual cells. Each starts with the same 500 USDT shared BTC/ETH
cash book; the capital of separate comparator/cost experiments is never
added or represented as concurrent owner accounts. Every cell retains its
full original fill trace and continuous 540-bar equity tape.

## Separate verification and reporting

`research/portfolio_v3_forward_independent_qa.py` imports no producer or
original engine. It rebuilds the fixed decision targets with Python
math/statistics, including BTC tie order, population volatility, original
rounding and anchored reviews. The separate QA action compares all targets
and the typed boolean review mask. Typed numeric target pairs are required;
boolean/string values cannot pass by NumPy coercion.

The independent Decimal implementation reconstructs every expected fill,
sell-before-buy cash flow, affordable purchase, fee, adverse slippage, risk
transition and terminal close from source prices. It compares every fill
field, actual execution/source time, all equity/cash/inventory marks and
all original metrics. Omitted/extra fills and rehashed false reports fail.
The full six-book/three-cost matrix is mandatory.

The verified report distinguishes fill events, FIFO-matched lot segments
and per-symbol flat-to-flat closed positions. Partial reductions do not
become separate positions. Monthly position/FIFO PnL uses exit month;
execution fees/slippage use actual execution month. Continuous equity PnL
is assigned to the source bar's UTC month, observed at bar close. Each
attribution reconciles to terminal net cash. Mean closed-position PnL is
null when no position closed. No minimum-trade-count rule is introduced.

Numerical QA does not prove positive edge. This fixed 90-day study is a
falsification review and cannot establish a profitable system by itself.
The report explicitly retains economic_edge_established=false,
paper_eligible=false, live_enabled=false and orders=0. A separate worker's
authenticated lease has not been proved by a local CLI; that flag remains
false. Manager/qualification/registry/Risk/Paper gates remain separate.

## Invocation and evidence

Current status needs no market inputs:

```sh
python -m scripts.nexus_portfolio_v3_forward_executor status
```

After the entire horizon and approved source QA, `run` requires
`--context-root`, `--archive-root`, `--capture-root`, `--source-qa` and a new
`--output` file. The separate `qa` action requires the same source paths,
the producer `--receipt` and another new `--output` file. Outputs are
write-once and linked paths are rejected. A later QA process reattests
source inputs rather than trusting the producer's embedded market claims.

Final local synthetic validation: **22 methods PASS** (10 bridge methods
plus 12 independent methods). Tests include the complete 18-cell original
producer/independent-QA path with all original producer functions disabled
during QA; causal prefix mutations; gaps and terminal risk triggers;
partials/FIFO/monthly reconciliation; incomplete/substituted/rehashed
matrices, source bars, targets, types, fills and marks; write-once output;
and rejection before input I/O at the actual current incomplete horizon.
All market values used in these tests are artificial.

`docs/evidence/portfolio-forward-executor-20261020/verification.json` binds
the code, contract, final test log and actual local environment. Native
Laptop2 tests are pending: RDC reported no online device and a read-only
Python-path probe returned INVALID_ARGUMENT/no online device. No native
test, installed deployment or completed financial study is claimed.
Hosted exact-head CI and physical Laptop2 verification remain review gates.

The existing preparation row remains BLOCKED; keep #2007/#2672 open.
Laptop1 remains the sole Paper writer. No owner install, journal, profile,
workflow, scheduler, monitor or VPS changes are included. Rollback removes
only these additive bridge, verifier, contract, test and evidence files.
