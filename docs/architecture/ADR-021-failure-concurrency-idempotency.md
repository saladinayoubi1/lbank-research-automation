# ADR-021 — Phase 4 Failure Taxonomy, Concurrency and Idempotency

Status: Gate 16 candidate
Parent: #510

## Decision

NEXUS uses one explicit failure taxonomy and bounded retry semantics. Duplicate work and concurrent state mutation are fenced by deterministic idempotency identity, ownership and compare-and-swap revision checks. Ambiguity fails closed.

## Failure taxonomy

The code-level classes are:

- `transient`
- `persistent`
- `corrupt_state`
- `stale_state`
- `provider_unavailable`
- `network_unavailable`
- `local_node_offline`
- `invalid_data`
- `policy_denied`
- `budget_resource_denied`
- `human_required`

Only transient/provider/network/local-node availability failures are retryable by default. Retry is always bounded by an explicit maximum attempt count. Policy, data, corruption, stale-state, budget/resource and human-required failures do not silently retry.

## Duplicate and ownership controls

`IdempotencyRegistry` binds an idempotency key to a canonical payload digest and deterministic owner. The same key with a different payload is rejected. A completed identical operation becomes a replay result rather than a second execution. An in-progress claim cannot be stolen by another owner.

`ExecutionFence` applies the same rule to signal/event/fill execution keys, preventing double fill/double execution while allowing deterministic replay of an already completed result.

## Concurrent state writes

`RevisionedStore` uses a lock plus expected-revision compare-and-swap semantics. Competing writers from the same revision produce exactly one winner; stale writers receive `RevisionConflict`. Reusing a commit idempotency key with different content is rejected. A candidate that fails canonical validation cannot replace the previous-valid snapshot.

The abstraction is authority-neutral and may be applied to event/config/ledger coordination; it does not itself authorize domain changes.

## Last-slice race

`ResourceSlice` makes the final allowed budget/resource unit atomic. When exhausted, later consumers receive `budget_resource_denied` instead of bypassing the bound.

## Tests

`tests/test_failure_concurrency.py` covers:

- complete frozen failure taxonomy;
- duplicate task replay and conflicting duplicate signal/event rejection;
- double-fill/double-execution fencing;
- concurrent event/config writes with no lost update;
- failed candidate commit preserving previous-valid state;
- race on the final allowed resource slice;
- bounded retry and non-retryable denial;
- deterministic ownership during retry handoff;
- deterministic failure alias classification.

Existing Gate 5/7/8/13 tests continue to own their domain-specific event, risk, execution and mission invariants. Gate 17 adds crash/chaos recovery across those boundaries.

## Authority effect

None. This Gate adds denial/fencing/reconciliation mechanics only. It cannot grant AI/provider/mission/risk/execution/live authority.

## Rollback / recovery

Rollback removes these generic coordination utilities without changing persisted paper/accounting contracts. Failed or stale candidates never replace previous-valid state. Restart/partial-write and full chaos recovery are exercised in Gate 17 using the frozen semantics from this Gate.

## Residual risk / next gates

Cross-process file locks and crash windows are recovery concerns for Gate 17. Security/privacy air-gap controls remain Gate 18. Measured contention/latency/resource ceilings remain Gate 19. Final same-SHA concurrency/recovery evidence remains Gate 20.
