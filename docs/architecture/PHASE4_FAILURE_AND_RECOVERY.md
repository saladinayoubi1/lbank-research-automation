# NEXUS Phase 4 Failure and Recovery Contract

Parent: #510
Version: `phase4-failure-recovery/v1`

## Failure classes
- transient
- persistent
- corrupt-state
- stale-state
- conflicting-state
- invalid-data
- provider-unavailable
- network-unavailable
- local-node-offline
- policy-denied
- budget/resource-denied
- human-required

## Retry policy
Blanket or unbounded retry is forbidden. Each retriable operation must declare retry count, backoff, timeout, idempotency semantics and terminal state. Persistent, corrupt, conflicting, policy-denied and human-required failures do not auto-loop.

## Previous-valid invariant
A candidate state, event stream, config, dataset, memory checkpoint or recovery artifact cannot replace previous-valid state until it passes the current versioned validation/policy contract. Ambiguity preserves previous-valid state.

## Idempotency / ownership
Every side-effect-capable workflow must define an idempotency key or deterministic ownership/lease mechanism. Duplicate task, signal, event, paper fill, config activation or retry after restart must not create duplicate authority effects.

## Required recovery scenarios
- process crash during write
- runner restart
- local laptop offline
- provider outage
- network interruption
- partial write/artifact
- corrupt/stale/conflicting state
- duplicate/reordered/gapped event stream
- interrupted paper operation
- malformed AI output
- unavailable/stale market data
- retry after ambiguous completion
- concurrent writers/race on last allowed risk/resource slice

## Recovery evidence
Recovery tests must record fixed source revision, policy/schema versions, initial previous-valid state, injected fault, deterministic reason/result, restored state digest and proof that no duplicate or unauthorized side effect occurred.

## Escalation
If recovery cannot prove a unique valid continuation, transition to blocked/quarantined/human-required; do not infer success from absence of an error.
