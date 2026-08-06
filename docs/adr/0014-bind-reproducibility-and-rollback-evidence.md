# ADR-0014: Bind reproducibility and rollback claims to verified evidence

- Status: Accepted for bounded offline validation
- Version: v1
- Production readiness: blocked

## Context

Comparing two directories and accepting a `schema_compatible: true` flag does not prove isolated clean builds, trusted source identity, a valid rollback target, or successful schema rollback. Mutable metadata can be replayed, substituted, downgraded, or authored by the same actor that produced the candidate.

## Decision

The release-recovery gate remains deny-by-default. A rollback record must use schema version 2 and policy `ADR-0014-v1`, remain explicitly unauthorized, and bind both current and previous-valid releases to exact manifest digests, source commits, and workflow-run IDs.

Schema and rollback claims must be carried in a separate bounded JSON evidence artifact referenced by a canonical repository-local path and bound by SHA-256. The evidence must match both manifest digests and record successful schema and rollback tests. This is internal consistency only; it does not authenticate builders, workflows, approvers, clocks, storage, or target environments.

## Trust boundaries

`source -> isolated builder -> output tree -> manifest/provenance -> rollback evidence -> offline verifier -> protected approver -> target environment`

Only the offline verifier and fixtures are repository-controlled. External builders, workflow identities, immutable storage, protected approvals, and target execution remain untrusted until separately attested.

## Threat and abuse cases

| Threat | Control | Residual risk |
|---|---|---|
| Replayed or substituted rollback record | Fixed schema/policy and exact source/workflow bindings | Workflow existence and identity are not remotely verified |
| Poisoned previous-valid tuple | Distinct version/digest and evidence binding | Storage immutability is not proven |
| Bare schema-compatibility assertion | Separate hashed evidence artifact | Evidence producer is not authenticated |
| Path traversal or symlink substitution | Canonical containment and symlink rejection | Hardlink, mount and TOCTOU semantics remain platform-dependent |
| Pre-authorized production rollback | Repository record must remain unauthorized | Protected approval system is external |
| Deterministic malicious outputs | Byte comparison catches drift only | Two identical outputs can still be malicious |
| Builder or dependency compromise | Exact source/workflow identifiers | Trusted builder and dependency lock evidence remain absent |

## Alternatives considered

1. Keep the original boolean-only record: rejected due to false-green risk.
2. Require signed attestations immediately: deferred pending owner-approved trust root, issuer policy and protected environment.
3. Remove the gate: rejected because bounded digest and path checks still reduce accidental substitution.

## Verification

Positive, negative and bypass tests cover identical outputs, changed/missing files, symlinks, mutable policy, invalid source commits, evidence tampering, previous-valid substitution, failed schema tests and path traversal. CI must pass on Linux, Windows and macOS.

## Rollback and recovery

Failed candidates are quarantined and must not modify previous-valid state. Recovery requires regenerating evidence from the expected source and workflow, recomputing digests, and revalidating under the current policy. Any production rollback requires protected approval outside mutable repository metadata and target-side verification.

## Residual blockers

Production reproducibility and rollback readiness remain blocked until two independently isolated builds, trusted provenance, immutable previous-valid storage, authenticated builders, protected approvals, measured migration/rollback execution and target-side verification exist.

## Obsolescence triggers

Re-review after changes to build system, dependency locking, workflow identity, provenance or attestation format, trust root, packaging/archive format, filesystem semantics, schema/migration model, approval boundary, target platform, or after any false-green, replay, builder compromise, rollback failure or previous-valid corruption incident.
