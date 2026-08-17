# NEXUS Phase 5 Typed Independent Verification

Status: Gate 4 candidate / shadow contract
Parent: #583
Depends on: Gates 1-3

## Decision

A producer result is not enough to mark a Phase 5 task `DONE`. Completion requires a versioned verification manifest bound to the exact current fenced attempt and to a verifier allowed by the task's verification policy.

Verification strength is part of the Gate-1 authorization `spec_digest`. Weakening `independent_trust_domain` to `independent_worker` therefore invalidates compatible runtime inheritance rather than silently reusing prior evidence.

## Worker trust domains

The Phase 5 mission registry gives every active worker an explicit trust domain:

- GitHub-hosted logical agents: `github-cloud`;
- real self-hosted Windows runner: `windows-local`;
- bounded external DeepSeek worker: `deepseek-external`.

DeepSeek remains non-verifier/advisory in the canonical registry.

The current trust-domain labels describe the execution/transport boundary used by Phase 5 policy. They are not cryptographic identity attestations by themselves. Gate 8/9 must bind actual workflow/runner metadata to these identities before a final cross-domain evidence claim is made.

## Verification modes

- `independent_worker`: verifier must be a different enabled verifier worker with the required verification capabilities.
- `independent_trust_domain`: all independent-worker rules plus verifier trust domain must differ from the producer trust domain.
- `owner_required`: no autonomous verifier is eligible; required for L4.

The task's `verification.required_capabilities` are separate from producer capabilities and are included in the task `spec_digest`.

## Verification subject

`nexus.phase5-verification.v1` binds:

- mission id/revision;
- task id and authorization `spec_digest`;
- active attempt id/number and fence generation;
- exact source SHA;
- policy version;
- producer worker id + trust domain;
- already-ingested producer result digest + producer evidence digest;
- canonical bounded artifact identities and SHA-256 digests.

A deterministic `subject_digest` covers this complete subject.

## Independent checks

A verification manifest contains a non-empty bounded set of canonical checks. Every check binds:

- unique check name;
- boolean pass/fail;
- SHA-256 digest of the check evidence.

`checks_digest` binds the set. The manifest decision is deterministic: `pass` only when every check passed; otherwise `fail`.

A pass marks the shadow task `DONE`. A failed verification marks it `BLOCKED` with a deterministic reason. An exact duplicate manifest is idempotent; a different second decision for the same accepted verification is rejected as a conflict.

## Deny-by-default cases

Reject completion for:

- stale/superseded attempt or fence;
- source SHA, spec, mission, task or policy substitution;
- producer result/evidence digest mismatch;
- same-worker verification;
- same trust domain when cross-domain verification is required;
- disabled/non-verifier/under-authority/missing-capability verifier;
- worker trust-domain registry substitution;
- malformed, duplicate, oversized or substituted artifact/check evidence;
- decision/check mismatch;
- autonomous verification of L4.

## Migration / claim boundary

This Gate 4 slice is additive and shadow-only. It proves the data contract and deterministic policy enforcement. It does **not** claim that a string worker id or trust-domain label authenticates the real executor. Gate 8 must integrate this manifest with actual dispatcher/run identity and shadow/cutover evidence; Gate 9 must prove the final source SHA with real self-hosted Windows evidence where cross-domain runtime semantics are required.

## Authority

Research/backtest/paper-only. No live-money execution, private exchange credentials, withdrawals, production promotion, billing, signing or deterministic Risk bypass is authorized.