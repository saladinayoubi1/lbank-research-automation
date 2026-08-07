# ADR-007: NEXUS cloud-fallback workflow change control

Status: Accepted
Version: 1.0.0

## Context

NEXUS uses a cloud-fallback GitHub Actions workflow as an auxiliary recovery/validation path. A fallback workflow can become a false-green source if it silently changes dependency resolution, skips tests, broadens permissions, diverges from the canonical test environment, or emits a checkpoint that consumers accept without binding it to the exact repository revision and run identity.

## Decision

1. The cloud-fallback workflow remains an auxiliary CI/recovery control, not production authorization and not evidence of live-trading readiness.
2. Test dependencies must come from the repository-owned locked development dependency set. If `tests/` exists and that lock is missing, the workflow fails closed.
3. The workflow runs dependency validation, compile validation, and the repository test suite before claiming fallback health.
4. Pull-request and `main` push execution are required so workflow changes are exercised before and after integration. Scheduled/manual execution may remain additive.
5. The workflow must stay registered in the versioned workflow-permissions policy. Permissions must remain least-privilege and explicitly reviewable.
6. Persisted checkpoint consumers must reject missing/unknown schema versions, non-true `checkpoint_valid`, non-success required step outcomes, malformed timestamps, stale/future checkpoints under an explicit freshness budget, and mismatched repository/SHA/run identity.
7. Changes to the fallback workflow, checkpoint schema/consumer, dependency source, permissions inventory, or trust assumptions require fixed-head green CI, mergeability confirmation, zero unresolved review threads, rollback notes, and ADR review.
8. Cloud-fallback success is not independent control-plane evidence while a candidate change can modify both workflow and authorizing policy/checks. Issue #106 remains the governing blocker for stronger self-authorization claims.
9. No workflow, agent, LLM, or auxiliary check may authorize real orders, credentials, billing, production mutation, or risk-policy changes.

Semantic changes to this decision require a new ADR version and must not silently reinterpret an existing checkpoint schema.

## Assets, actors, trust boundaries, and entry points

Protected assets are truthful CI/recovery health, exact-head traceability, previous-known-good recovery evidence, least-privilege workflow authority, and prevention of stale/replayed checkpoints being represented as current.

Relevant actors/failures include maintainers, compromised automation, malicious or stale artifact suppliers, dependency/runner drift, accidental workflow weakening, and consumers using an obsolete contract.

Trust boundaries are `repository/ref -> GitHub workflow -> step outcomes -> persisted checkpoint -> consumer`, plus `workflow/policy change -> repository review/ruleset authority`. Entry points include workflow YAML, dependency locks, status schema fields, uploaded artifacts, consumer expectations, and permissions-policy inventory.

The workflow may attest only to bounded test/checkpoint facts. Independent authorization remains outside this control until Issue #106 is satisfied.

## Threats and abuse cases

- missing or modified lock file;
- dependency conflicts hidden by successful installation;
- compile/test step disabled, skipped, neutral, cancelled, or malformed;
- workflow permissions widened or workflow removed from inventory;
- producer sets `checkpoint_valid=true` while required outcomes disagree;
- legacy or unknown schema accepted as healthy;
- stale checkpoint replayed for a newer SHA/run;
- future timestamp or malformed clock data hides replay;
- repository, source SHA, or run ID substituted;
- workflow and policy/checks weakened together to create self-authorized green evidence;
- previous-known-good evidence overwritten during failed recovery;
- claims that exceed the bounded evidence produced by the fallback job.

## Deny-by-default policy

A checkpoint is invalid unless the consumer recognizes the exact schema and mode, requires literal `checkpoint_valid=true`, independently rechecks every required step outcome as `success`, verifies expected repository and source SHA, verifies run identity when available, validates an offset-aware timestamp, and enforces an explicit positive freshness budget when freshness is claimed.

Missing, malformed, stale, future, conflicting, unsupported, or mismatched evidence is quarantined and must not replace previous-known-good evidence. Consumers must not downgrade to legacy interpretation when schema validation fails.

Simultaneous workflow/policy weakening remains residual risk and cannot be promoted to independent authorization evidence until Issue #106 provides an authority outside the candidate change set plus bypass tests.

## Compatibility and schema evolution

Checkpoint schema v2 adds exact step outcomes, source and runner SHA distinction, run attempt/event identity, and `checkpoint_valid` with deterministic invalid reasons. Consumers that do not explicitly support schema v2 must fail closed. Future schema changes require a version bump, compatibility plan, migration or dual-read policy where justified, regression tests, rollback instructions, and ADR review.

## Rollback and recovery

Rollback restores the last known-good workflow, policy inventory, checkpoint producer, and compatible consumer tuple. Do not silently reinterpret v2 evidence using legacy semantics.

Recovery procedure:
1. quarantine the failed or unverifiable checkpoint and preserve previous-known-good evidence unchanged;
2. restore the previous-valid workflow/policy/producer/consumer revisions from Git;
3. rerun all required repository checks on one fixed rollback SHA;
4. produce a new checkpoint and verify exact repository/SHA/run binding, supported schema, required step outcomes, timestamp/freshness policy, and zero invalid reasons;
5. only then replace the quarantined candidate as the active fallback health record.

A recovery exercise is considered successful only when an intentionally invalid candidate is rejected without mutating previous-known-good state, followed by successful validation of the restored tuple on a fixed SHA.

## Observability and evidence

Merge evidence consists of exact head SHA, workflow-run conclusions for that SHA, mergeability state, review-thread state, reviewed workflow/producer/consumer/ADR diff, and executable positive/negative/replay tests. A green result from a different SHA is not acceptable evidence.

## Residual risk

This control does not provide independent control-plane authorization, signed provenance, immutable runner identity, cross-platform fallback execution, production deployment approval, or live-execution safety certification. GitHub Actions semantics and repository rules remain external dependencies.

## Obsolescence triggers

Revisit this ADR on any material change to:
- GitHub Actions outcome semantics, including `skipped` or `neutral` behavior;
- required-check or repository ruleset authority;
- workflow trigger architecture or permission model;
- checkpoint schema, consumer contract, freshness budget, or artifact retention;
- Python/runner major version, dependency lock format, or repository test entrypoint;
- provenance/signing or trusted-builder model;
- resolution or redesign of Issue #106;
- any false-green, replay, recovery, or checkpoint-substitution incident.

## Related work

- PR #109 — cloud-fallback CI gate repair
- PR #117 — fail-closed checkpoint semantics and consumer validation
- Issue #94 — NEXUS architecture baseline and change-control gates
- Issue #106 — independent protection against control-plane self-authorization
