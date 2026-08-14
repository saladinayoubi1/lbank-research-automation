# ADR-0230 — Durable Gap-Repair Checkpoint Recovery

Status: ACCEPTED FOR GATE-2 VALIDATION
Date: 2026-08-14
Issue: #230

## Context

Bounded gap repair must preserve fairness across process restarts without allowing stale, corrupt, ambiguous, or concurrently owned state to authorize stronger recovery claims. The implementation is research-only and grants no production, live-trading, credential, billing, signing, or release authority.

## Decision

Checkpoint identity is `(symbol, timeframe, ordered gap-set digest, schema version)`. A cursor is meaningful only inside that exact identity. Gap-set reorder/change, symbol/timeframe mismatch, unsupported schema, impossible cursor, malformed state, or deletion after prior initialization fails closed.

Every checkpoint operation uses one canonical path after rejecting symlink substitution. Relative/`..`/case-normalized aliases therefore resolve to one checkpoint and one ownership domain rather than creating parallel state.

Checkpoint publication is transactional: write same-directory temporary content, flush and fsync it, then atomically replace the destination. POSIX replacement is followed by parent-directory fsync. Windows uses `MoveFileExW` with `MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH`; the destination file is then fsynced. Initialization-marker publication follows the same durable pattern.

Cross-process ownership is kernel-managed. POSIX uses `fcntl.flock`; Windows uses `msvcrt.locking`. The coordination file is persistent metadata only and is never itself proof of ownership. Kernel ownership is released when a process exits, including abnormal termination, so recovery does not depend on PID age, wall-clock heuristics, or deleting a presumed orphan sentinel.

A repair worker holds ownership from checkpoint read through bounded network repair, durable market-data save, post-save gap-set recomputation/remap, and checkpoint commit. Cursor advancement never precedes durable market-data publication. If a crash happens after data save but before cursor commit, re-attempting a bounded window is acceptable; advancing ahead of durable data is not.

## Deny-by-default behavior

The following do not produce a starvation-free or recovery-complete claim: corrupt or partial checkpoint, stale/reordered gap identity, unsupported schema, cursor out of range, wrong series identity, deleted initialized checkpoint, concurrent ownership conflict, symlink/path substitution, ambiguous post-save state, or zero-progress/source-unavailable responses. Repair remains bounded and reports an explicit degraded outcome.

## Fairness and liveness boundary

Network requests and rounds remain bounded. Persisted cursor state rotates bounded work across clean process restarts. After successful data publication, the cursor is remapped against the authoritative post-save gap set so a removed/recovered gap cannot make the next cursor invalid or regress fairness. `source_unavailable` windows remain explicit and cannot monopolize unbounded retries.

## Threat / failure / bypass coverage

Required regression coverage includes process restart/resume, deterministic bounded rotation, corrupt checkpoint, stale/reordered gap set, symbol/timeframe mismatch, unsupported schema, cursor bounds, checkpoint deletion, concurrent writers, abnormal owner exit, canonical path aliases, symlink substitution, crash windows around data-save/cursor-commit, durable replacement behavior, post-save cursor remap, source-unavailable/no-progress behavior, and transaction ordering.

Control-plane policy/test co-weakening is not delegated to this checkpoint implementation. It is independently evaluated by the repository's protected trusted-base `control-plane trusted guard`; Gate 2 must not modify the frozen Gate 4 control-plane paths to make itself pass.

## Alternatives rejected

- Process-local cursor: loses fairness on restart.
- Timestamp-only cursor: is not bound to ordered gap identity.
- Unbounded retry: can hide unavailable-source conditions and monopolize budget.
- Sentinel-file ownership: can deadlock after abnormal exit.
- PID/age-based stale-lock breaking: unsafe under PID reuse, clock drift, slow workers, and shared storage.
- Best-effort or swallowed durability errors: creates a false durability claim.
- Retargeting stale stacked branches as final evidence: can carry unrelated ancestry and invalidate independent guard results.

## Rollback

Rollback code, checkpoint semantics, this ADR, and regression tests together to the previous-known-good bounded fail-closed behavior. Incompatible checkpoint/marker/lock artifacts are quarantined rather than reinterpreted. Do not retain a newer checkpoint format as authoritative under older code.

## Recovery replay

On one fixed final SHA and fixed gap set: run a bounded repair; persist data/checkpoint; terminate the process; restart from clean process state; verify the next eligible gap is selected; continue bounded attempts until all reachable gaps are exercised; verify unavailable gaps remain explicit without starving later gaps; exercise ownership contention and abnormal owner exit; then rerun readiness/provenance validation.

## Residual risk and completion condition

Filesystem power-loss semantics ultimately depend on the supported OS/filesystem guarantees behind fsync/`MOVEFILE_WRITE_THROUGH`; the implementation therefore claims only the documented supported-platform durability contract, not universal storage durability. Gate 2 closes only when this ADR, implementation, regression suite, restart replay, independent trusted guard, mergeability/review state, and exact-final-head CI are aligned on one clean SHA.

## Obsolescence triggers

Re-review when gap ordering/identity, worker concurrency, persistence backend/filesystem support, lock design, request budget/max-round policy, source pagination/provider semantics, checkpoint/status schema, or any incident showing repeated-window starvation changes.
