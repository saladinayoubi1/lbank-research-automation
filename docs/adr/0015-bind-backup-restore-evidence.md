# ADR-0015: Bind backup and restore claims to bounded evidence artifacts

- Status: Accepted for offline validation only
- Version: v1
- Production readiness: blocked

## Decision

The backup/restore verifier remains deny-by-default. The exercise envelope must use schema version 2 and policy `ADR-0015-v1`, bind to an exact source commit and workflow-run ID, and remain explicitly unauthorized for production.

Backup storage claims must be carried in a separate regular JSON artifact referenced by a canonical repository-local path and bound by SHA-256. The artifact must match the exact backup ID and record independent storage, encryption verification, retention verification, immutable storage-object version, key owner, retention period, and backup creation time.

Restore evidence must be fresh, meet declared RPO/RTO, cover the complete required scope, reject corruption and missing-backup cases, verify restored bytes and sizes, and include target-side verification.

## Threats and residual risk

This rejects stale, tampered, substituted, path-traversing, symlinked, preauthorized, incomplete, or digest-mismatched evidence. It does not authenticate the workflow, storage provider, key owner, approver, trusted clock, or target environment. A single actor can still fabricate internally consistent unsigned evidence.

## Rollback and recovery

Failed candidates are quarantined and must not replace previous-valid evidence. Recovery requires regenerating the exact backup artifact and restore envelope, recomputing digests, and revalidating under the current policy. Production restore remains blocked pending protected approval and external credentials.

## Production blockers

Trusted signed attestations, protected production approval, external backup credentials, independently retained immutable backup storage, real restore execution, target-system evidence, billing decisions, and credential/key lifecycle remain outside this repository gate.
