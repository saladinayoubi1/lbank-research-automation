# NEXUS Phase 5 Attempt Fencing

Status: Gate 3 candidate / shadow contract
Parent: #583
Depends on: Gates 1-2

## Decision

Every autonomous execution attempt receives a monotonically increasing per-task `fence_generation` and an immutable attempt identity. A worker result is accepted only when it matches the task's current fence, active attempt, lease, worker, source SHA and authorization `spec_digest`.

This is intentionally stronger than lease-id matching alone: after reassignment, an older worker can retain its old payload/artifact, but its lower fence is permanently stale.

## Attempt identity

`nexus.phase5-attempt.v1` binds:
- mission id;
- task id;
- task `spec_digest`;
- attempt number;
- fence generation;
- lease id;
- worker id;
- exact source SHA.

The deterministic SHA-256 `attempt_id` is derived from those fields. `state_generation_issued` is retained as audit context but is not used to invalidate an otherwise current task merely because unrelated state advanced.

## Monotonicity and bounded retry

- reissuing the exact same active lease/worker/spec/source is idempotent;
- a different lease or worker supersedes the active attempt and increments the fence;
- prior history is preserved rather than overwritten;
- attempt history is bounded; reaching the bound rejects a new attempt without mutating the current valid one;
- L4 tasks cannot receive autonomous attempts.

## Result ingestion

`nexus.phase5-attempt-result.v1` must exactly match the current fenced attempt.

Reject:
- old fence or old attempt id;
- worker/lease substitution;
- task/mission/spec substitution;
- source-SHA substitution;
- invalid/oversized/non-canonical evidence;
- conflicting second result for an already-ingested attempt.

An exact duplicate result delivery is a no-op, which makes callback retries idempotent.

The attempt history records only bounded result/evidence digests and outcome metadata. Gate 4 adds the typed independent evidence manifest required before a task can be treated as independently verified/DONE.

## Persistence

Gate 1 runtime merge preserves `fence_generation`, `active_attempt_id` and `attempt_history` only while the task `spec_digest` remains identical. A task-spec change therefore cannot inherit a prior fenced completion history as current authority.

Gate 2 durable StateStore provides the generation-CAS boundary that persists these task-local fencing fields. Gate 8 owns shadow/cutover integration into the canonical dispatcher.

## Authority

Research/backtest/paper-only. No live-money execution, private credentials, withdrawals, production promotion, billing, signing or deterministic Risk bypass is authorized.