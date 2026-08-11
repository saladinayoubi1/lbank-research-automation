# ADR-0230 — Durable Gap-Repair Checkpoint Recovery

Status: PROPOSED / FAIL-CLOSED
Date: 2026-08-11
Issue: #230

## Context

NEXUS gap repair is research-only and must never fabricate market data or promote an invalid/gapped series to research-ready. Bounded repair uses a persisted cursor so repeated invocations do not restart from the same oldest unavailable window. A correct recovery claim therefore depends on both durable checkpoint state and exclusive ownership of the read/network/save/cursor-commit transaction.

This ADR defines the claim boundary for the checkpoint work in PR #362. It does not authorize production deployment, live trading, credentials, signing, billing, or any financial action.

## Decision

### Authoritative identity

Checkpoint identity is the tuple:

`(symbol, timeframe, ordered gap-set digest, checkpoint schema version)`

The cursor is positional within that exact ordered gap set. Reordering, adding, or removing gaps changes identity. Symbol/timeframe aliases are not equivalent unless an independently reviewed mapping contract says so.

### Persistence semantics

1. A checkpoint write uses a same-directory temporary file, file flush/fsync, and atomic replace.
2. Recovered market-data rows must be durably saved before the fairness cursor advances.
3. The initialized marker distinguishes first use from deletion after prior initialization.
4. Corrupt, malformed, unsupported-version, stale-gap-set, wrong-series, impossible-cursor, missing-after-initialization, or ownership-conflict state fails closed before a stronger recovery claim.
5. Current implementation fsyncs the checkpoint/marker file contents. It does **not** yet prove containing-directory entry durability on every supported filesystem. Until that is implemented and tested, claims are limited to file-content durability after the relevant directory entry is visible; crash-durable rename/creation across all supported filesystems remains unproven.

### Ownership semantics

A repair worker must hold one exclusive checkpoint ownership token from before checkpoint read and network repair through durable data save and cursor commit. A concurrent owner conflict is a hard degraded/fail-closed condition; no network repair should begin under ambiguous ownership.

A leftover lock after abnormal termination is not safe to delete solely because of age or a stored PID: PID reuse, clock changes, long-running repair, and cross-host/shared-storage execution can make those signals ambiguous. Automatic stale-lock breaking is therefore forbidden until owner liveness can be proven by a versioned lease/locking contract. For the current implementation, an orphaned lock requires explicit recovery/quarantine and the starvation-free claim remains unavailable while it exists.

## Bounded repair policy

- Network requests and rounds remain explicitly bounded by existing repair policy.
- `source_unavailable` or zero-progress windows must not cause unbounded retry.
- Persistent cursor state may rotate work across bounded invocations, but it is not permission to weaken integrity or freshness gates.
- A crafted status file or checkpoint may never turn a zero-progress loop into a successful/recovery-complete result.

## Threat and failure model

| Case | Required behavior |
|---|---|
| Process restart | Resume from the persisted cursor only when identity and schema validate. |
| Gap set changed/reordered | Reject old checkpoint as stale; no silent cursor reinterpretation. |
| Corrupt/partial checkpoint | Reject before network I/O; preserve evidence for diagnosis. |
| Cursor out of range | Reject as impossible state. |
| Symbol/timeframe mismatch | Reject as identity mismatch. |
| Unsupported schema/downgrade | Reject; never silently coerce to a known version. |
| Checkpoint deleted after initialization | Reject; never silently reset to oldest-first. |
| Concurrent repair workers | Exactly one owner may enter the transaction; contenders fail closed before network I/O. |
| Worker crashes while lock exists | Do not age/PID-break automatically; quarantine/recovery proof is required. |
| Crash after data save but before cursor commit | Reprocessing the same bounded window is acceptable; cursor must not advance ahead of durable data. |
| Crash after cursor decision but before durable data save | Transaction ordering must prevent this state from becoming authoritative. |
| Directory-entry durability loss | Strong crash-durability claim remains blocked until directory fsync/portable equivalent is tested. |
| Alternate checkpoint/status path | Must not bypass canonical path/identity policy. |
| Policy and tests weakened together | Independent deterministic policy checks/review evidence are required; green tests alone are insufficient. |

## Alternatives rejected

- **Process-local cursor:** loses fairness state on restart.
- **Timestamp-only cursor:** does not bind to ordered gap-set identity and can be replayed against changed gaps.
- **Unbounded retry:** can monopolize request budget and hide unavailable-source conditions.
- **Age-based orphan-lock deletion:** can evict a live slow worker.
- **PID-only orphan-lock deletion:** PID reuse and host ambiguity can misidentify ownership.
- **Treating green CI as recovery authority:** CI does not prove crash replay, filesystem semantics, or independent policy enforcement by itself.

## Positive validation required before completion

1. Fixed gap-set bounded round writes checkpoint, process state is discarded, and a clean invocation selects the next eligible gap.
2. Repeated bounded invocations reach every eligible deferred gap within the documented bound.
3. Recovered data is saved before cursor advancement.
4. Ownership is held across checkpoint read, network repair, data save, and cursor commit.
5. Exact final head passes all required CI, is mergeable, and has no unresolved review thread.

## Negative/bypass validation required before completion

Must cover corrupt checkpoint, stale/reordered gap set, wrong symbol/timeframe, unsupported version, cursor out of range, deleted initialized checkpoint, concurrent owner, lock/path substitution, alternate status/checkpoint path, crash windows around data-save/cursor-commit, and policy/test co-weakening. Rejected cases must not emit a starvation-free or recovery-complete claim.

## Rollback

Rollback is atomic at the feature level: revert checkpoint ownership/integration code, checkpoint schema assumptions, this ADR, and associated tests together to the previous-known-good bounded fail-closed repair behavior. A newer checkpoint format must never be retained as authoritative under older code. Existing incompatible checkpoint/marker/lock artifacts are quarantined rather than interpreted.

## Recovery replay

On one fixed repository head and fixed dataset/gap set:

1. Record exact code SHA, dataset/gap-set digest, checkpoint path/schema, and bounded repair parameters.
2. Run one bounded repair transaction and persist recovered data plus checkpoint.
3. Terminate the worker/process.
4. Restart from clean process state and verify selection advances according to persisted cursor.
5. Exercise a source-unavailable window and verify later windows still receive bounded attempts.
6. Exercise a crash/failure before cursor commit and verify cursor never advances ahead of durable data.
7. Exercise ownership contention and orphan-lock handling; ambiguous ownership must remain fail-closed.
8. Rerun data readiness/provenance validation. No stronger recovery claim is restored unless all deterministic gates pass on the same fixed final head.

## Residual risks / current blockers

- Safe orphan-lock recovery is not yet implemented; ambiguous leftover locks remain manual/quarantine recovery events.
- Portable containing-directory crash durability is not yet proven across supported filesystems.
- Adversarial crash/path/lock bypass replay and policy/test co-weakening evidence are incomplete.
- Therefore #230 remains open and restart-starvation freedom is non-authoritative.

## Obsolescence triggers

Re-review this ADR when gap ordering/identity changes, worker concurrency changes, persistence backend or filesystem support changes, lock/lease design changes, request budget or max rounds change, source pagination semantics change, a new market-data provider is added, status/checkpoint schema changes, or any incident demonstrates repeated-window starvation after restart.
