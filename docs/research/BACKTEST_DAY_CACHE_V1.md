# Vectorized day keys for the existing composite backtest

## Architecture precheck

- Change: compute each candle's calendar-day key once before the existing fill loop.
- System Map nodes: RES-32, VAL-40, QA-41.
- Existing component: nexus_composite_strategy_research.backtest; no new simulator or strategy.
- Why: the first distinct-host v6 verification expired at 600 seconds without a proof. A bounded diagnostic completed decoding, features and signal, then expired inside the backtest at the scalar timestamp day-floor call. That call currently repeats for every candle. The diagnostic used cProfile, so its durations are not an uninstrumented speed benchmark.
- Execution lane: local regression preparation and isolated Laptop1 independent native benchmark; Laptop2 remains Research primary and Laptop1 remains the single owner writer.
- Data/provenance: unchanged immutable Bybit Spot replay archive; original study source 8899ec6bec4927fc39795f2867be91e2431178c6 and original report/receipts remain bound to that source.
- Upstream: existing closed-candle timestamps, signals, risk/cost contract and exact input identities.
- Downstream: exploratory backtests and numerical QA only; no qualification, registry, owner or Coordinator transition.
- Authority: Research-only. Demo admission=false, Live=false. The 500 USDT owner journal/install is untouched.
- Duplicate-work check: older completed v5 jobs and the completed v6 producer are not rerun. The expired full verifier is preserved; only a one-cell diagnostic/benchmark is used for performance diagnosis. No parallel runner, runtime or Paper writer is created.
- Failure: malformed/noncanonical object timestamps retain scalar conversion behavior; timezone-aware arrays retain their timezone day boundaries. Mismatching metrics or source identities fail closed.
- Rollback: revert the additive day-cache helper and loop lookup; prior immutable evidence remains available.
- Tests: frozen scalar-reference golden metrics across midnight, daily loss pause, drawdown halt, risk variants, costs, UTC/naive/offset/object/mixed timestamp forms; vector/scalar day parity including a DST transition; count scalar calls on the canonical vector path.
- Independent QA: exact-head native tests and a bounded one-cell comparison against the original report are required. They do not complete the original full-grid QA or Decimal audit.
- Deployment: research branch only; no owner installation or cutover.
- Evidence for completion: reviewed code identity, exact-head regression results and honest native timing/comparison evidence. Source merge and strategy qualification remain separate gates.

## Semantics

Pandas' vector day-floor operation uses the same timezone calendar rule as scalar Timestamp.floor("D"). Non-datetime object inputs retain the original scalar conversion. The fill loop's daily reset reads the cached day key; signals, next-open fills, fees, slippage, cash, exposure, stop/target priority and daily/drawdown limits are unchanged.
