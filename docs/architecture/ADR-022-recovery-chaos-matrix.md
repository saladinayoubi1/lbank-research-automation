# ADR-022 — Phase 4 Recovery and Chaos Matrix

Status: Gate 17 candidate
Parent: #510

## Decision

Recovery is previous-valid-state first. A candidate state becomes authoritative only after complete deterministic validation and atomic publication. Any ambiguous, partial, stale, corrupt or conflicting candidate is rejected; recovery never expands authority.

`AtomicRecoveryStore` publishes a candidate only after canonical validation and expected-revision validation. Fault injection after validation or immediately before publication leaves the previous durable snapshot unchanged. `RecoverySupervisor` deterministically restores the supplied validated checkpoint for each frozen failure scenario.

## Frozen chaos matrix

The implementation explicitly classifies and exercises:

1. process crash;
2. runner restart;
3. local laptop offline;
4. provider outage;
5. partial write;
6. corrupt/stale/conflicting state;
7. duplicate/reordered events;
8. interrupted paper operation;
9. malformed AI output;
10. unavailable/stale/ambiguous market data;
11. partial artifact/evidence failure.

## Fail-closed behavior

- Process/runner restart restores the last validated durable checkpoint.
- Local-node/provider outages preserve state and expose degraded status.
- Partial/corrupt/stale/conflicting candidates cannot publish.
- Duplicate/reordered/gapped event windows are rejected before replay.
- Interrupted paper operations restart from the durable checkpoint rather than assuming a fill.
- Malformed AI output has no state authority.
- Unavailable/stale/ambiguous market data blocks progress and preserves state.
- Partial evidence cannot be promoted as complete evidence.

## Integrity

Checkpoints carry revision, canonical state and SHA-256 state digest. Restore verifies the digest before replacing current state. Event windows require unique IDs and strictly contiguous increasing sequence numbers.

## Tests

`tests/test_recovery_chaos.py` verifies the full matrix, before-publish crash windows, checkpoint restoration, degraded offline/outage modes, corrupt/stale candidate rejection, duplicate/reordered event rejection, interrupted paper operations, malformed AI output, stale market data, partial evidence and tampered checkpoint rejection.

## Authority effect

None. Recovery can restore or block only. It cannot approve Risk, create paper fills, grant provider/AI authority, add credentials, or create live/production/billing/signing paths.

## Rollback

Rollback removes the generic recovery matrix without altering the existing Gate 5 event store or Gate 8 paper accounting schema. Existing domain recovery remains previous-valid and fail-closed.

## Residual risk / next gates

Gate 18 independently enforces security/privacy and the paper/live air gap. Gate 19 measures performance/resource ceilings. Gate 20 must prove these recovery semantics against the complete final same-SHA paper and AI-control E2E path, including real Windows evidence where runtime behavior matters.
