# ADR-0013: Bind disaster-recovery evidence before accepting bounded claims

- Status: Accepted for offline validation only
- Version: v1
- Production readiness: blocked

## Context

The prior gate validated a self-authored exercise summary. Bare booleans, role labels and paths do not prove that a restore, rollback or scenario drill occurred. Evidence may be substituted, replayed, stale, linked to the wrong exercise, or supplied by one principal under several aliases.

## Decision

The offline verifier must fail closed unless every required scenario references a regular, non-symlink JSON artifact inside the evidence root and supplies its lowercase SHA-256 digest. The artifact must bind to the immutable exercise ID and exact scenario name and must record observed execution and recovery verification.

The exercise envelope must use schema version 2 and bind to an exact 40-character source commit, positive workflow-run ID and policy version `ADR-0013-v1`. Production authorization embedded in repository evidence is always rejected.

This control proves only deterministic internal binding of supplied offline files. It does not authenticate a builder, approver, backup provider, target environment or trusted clock. Signed attestations and protected approvals remain required before production claims.

## Trust boundaries

`backup producer -> backup storage -> recovery runner -> evidence artifacts -> offline verifier -> protected approver -> target environment`

The repository controls only the offline verifier and test fixtures. Every external boundary remains untrusted until separately authenticated and attested.

## Threat and abuse cases

| Threat | Deny-by-default control | Residual risk |
|---|---|---|
| Missing or substituted scenario record | Required file, bounded size and SHA-256 match | Same actor may author envelope and record |
| Wrong exercise or scenario | Exact exercise ID and scenario binding | Exercise ID is not externally authenticated |
| Path traversal or symlink substitution | Canonical relative path, containment check, symlink rejection | Hardlink and TOCTOU resistance is limited by local filesystem semantics |
| Replay or stale evidence | Fixed 30-day freshness policy | Clock trust is not established |
| Mutable source/workflow claim | Exact commit format and positive run ID | Workflow identity and run existence are not remotely verified |
| Role aliasing | Distinct role strings | Distinct authenticated principals are not proven |
| Repository-contained production approval | Explicit rejection | External approval system is not implemented |

## Alternatives considered

1. Accept schema-valid summaries: rejected because this creates false assurance.
2. Require signed GitHub artifact attestations immediately: deferred because trust-root and identity policy require owner approval and external infrastructure.
3. Remove the gate: rejected because bounded structural and digest checks still reduce accidental and trivial substitution failures.

## Verification

Positive, negative and bypass tests cover valid binding, tampered records, wrong exercise/scenario, missing files, symlinks, wrong digests, mutable source/policy bindings, stale evidence, role reuse, traversal and duplicate scenarios. CI must run cross-platform.

## Rollback and recovery

A failed candidate is quarantined and previous-valid evidence is not modified. Recovery requires regenerating the exact scenario records from the expected exercise, recomputing digests, and revalidating under the current policy. Reverting this ADR or verifier must not be interpreted as production approval.

## Obsolescence triggers

Re-review after changes to attestation format, workflow identity, trust root, backup provider, target environment, filesystem semantics, evidence schema, freshness policy, approval boundary, or after any false-green, replay, builder compromise, recovery failure or target-verification incident.
