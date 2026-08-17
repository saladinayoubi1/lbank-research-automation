# ADR-024 — Phase 4 Performance and Resource Bounds

Status: Gate 19 candidate
Parent: #510
Policy: `phase4-resource/v1`

## Decision

Phase 4 defines explicit measurable soft/hard bounds for every frozen performance/resource surface. Exceeding a soft bound degrades service; exceeding a hard bound denies the affected work. Resource pressure never increases authority, disables Risk, bypasses the paper/live air gap or silently creates unbounded retry/concurrency.

## Governed metrics

The versioned default policy covers:

- API latency (`ms`);
- dashboard latency (`ms`);
- AI Chat timeout (`ms`);
- agent timeout (`ms`);
- queue latency (`ms`);
- replay/event processing (`ms`);
- backtest runtime (`ms`);
- research runtime (`ms`);
- storage (`bytes`);
- log retention (`days`);
- runner concurrency (`workers`);
- provider spend (`microUSD`);
- provider usage (`tokens`);
- CPU (`millicores`);
- memory (`bytes`);
- job runtime (`ms`).

`ResourceGuard` requires the complete frozen metric set and rejects unknown metrics rather than treating them as unbounded.

## Measurement evidence

`MeasurementWindow` records bounded integer-only samples and derives deterministic nearest-rank p50/p95 evidence. A window cannot grow beyond its configured capacity. `evidence_snapshot()` marks evidence incomplete until every frozen metric has a measured summary; missing metrics are explicit.

## Exhaustion and concurrency

`ConcurrencyBudget` is non-blocking and atomic. When all worker slots are used, further work is denied immediately. Re-acquiring the same work identity is idempotent; releasing an unowned slot fails.

`QuotaBudget` provides atomic monotonic reservations for provider tokens/spend and other consumable quotas. Duplicate reservation IDs replay only when the requested amount is identical. A reservation that would exceed the hard limit is denied without partial consumption.

## Default soft/hard behavior

- measured value `<= soft` -> `allow`;
- `soft < value <= hard` -> `degrade`;
- `value > hard` -> `deny` / `ResourceExhausted` when the caller requires capacity.

The limits are conservative Phase 4 operating defaults rather than claims of exchange-grade production SLOs. Gate 20 binds measured final-flow evidence to the final fixed SHA.

## Tests

`tests/test_resource_bounds.py` covers:

- complete metric inventory and explicit units;
- exact soft/hard boundaries for every metric;
- unknown/incomplete policy fail-closed behavior;
- rejection of binary float, negative and boolean measurements;
- deterministic p50/p95 and bounded measurement windows;
- p95-driven degradation;
- runner concurrency race with no oversubscription;
- idempotent concurrency ownership and strict release;
- provider token/spend quota exhaustion and last-slice races;
- complete/incomplete Gate 19 evidence snapshots.

## Authority effect

None. This Gate allocates/denies resources only. It cannot authorize strategy qualification, Risk, paper execution, provider privilege, private exchange access or live/production actions.

## Rollback and recovery

A failed or missing resource policy is not interpreted as unlimited capacity. The validator requires the complete frozen metric set. Resource reservations are process-local evidence/guards and do not replace portfolio/accounting/event truth. Recovery from process loss reconstructs authoritative trading state from Gate 5/8/17 mechanisms, while resource consumers must reacquire bounded capacity.

## Residual risk / Gate 20

Gate 20 must collect same-SHA measurable evidence for the full paper path and prove overload/degraded behavior remains fail-closed while dashboard/audit/replay state stays consistent. Real Windows self-hosted runtime evidence is required where the frozen E2E scope says local runtime behavior matters.
