# ADR-0011: Secret-bearing one-time workflows must self-retire and use explicit dispatch

- **Status:** Proposed
- **Version:** 1.0.0
- **Date:** 2026-08-05
- **Decision owner:** NEXUS security governance
- **Review date:** 2026-09-05
- **Supersedes:** PR #50 commit-message-triggered Zotero workflow
- **Obsolescence triggers:** GitHub introduces native expiring workflows; OIDC/workload identity replaces static Zotero secrets; repository secret policy changes; a workflow-trigger bypass or duplicate-write incident occurs.

## Context and threat model

PR #50 added a push-triggered workflow that held Zotero write credentials and attempted to behave as a one-time operation by comparing the complete merge commit message with one fixed string. The squash merge commit contained a title and body, so the equality test did not match and the intended upload did not run. The workflow nevertheless remained enabled on `main`, meaning any future push with the exact full message could invoke the secret-bearing write path.

Assets: Zotero API key, target-library integrity, evidence metadata, workflow auditability, and confidence that a claimed one-time operation cannot recur.

Trust boundaries: maintainer/automation -> Git commit metadata -> GitHub push event -> workflow expression -> secret-bearing runner -> Zotero API.

Adversaries and failure actors: compromised maintainer session, mistaken commit author, reused automation text, workflow-maintenance error, or an attacker who can cause an authorized push.

## Evidence triangulation

### Official standard and platform guidance

- NIST SP 800-53 Rev. 5 AC-6 and SI-7 require least privilege and protection of software/information integrity. A standing workflow with external-write secrets violates the intended minimization when the operation is complete.
- GitHub Actions security guidance treats workflows as privileged code and recommends minimizing token permissions, constraining secret access, and avoiding unsafe trigger/input patterns.

### Independent academic evidence

Koishybayev et al., *Characterizing the Security of GitHub CI Workflows*, USENIX Security 2022, identifies admittance control, execution control, code control, and secret access as fundamental CI/CD security properties. Their large-scale study shows that workflow privilege and trigger design are systemic attack surfaces.

### Implementation or incident evidence

Codecov's April 2021 Bash Uploader incident demonstrated that CI components executing with environment variables and repository context can become a supply-chain exfiltration path. The direct lesson is to minimize the lifetime and reachability of secret-bearing automation.

### Limitation and opposing view

Only users able to push to `main` could reproduce the exact trigger, so exploit likelihood is lower than for an untrusted pull-request trigger. However, the workflow's purpose was explicitly one-time, and privileged-account compromise or operator error remains in scope. Commit-message equality is also brittle and cannot prove uniqueness, intent, or successful prior execution.

## Decision

1. Remove the persistent `zotero-one-time-upload.yml` workflow immediately.
2. Secret-bearing external writes default to deny and require explicit `workflow_dispatch` with a boolean apply gate, bounded input validation, read-only repository permissions, and existing protected secrets.
3. Do not use commit messages, branch names, labels, PR titles, or other mutable metadata as authorization tokens.
4. One-time workflows must either be deleted in the same reviewed change after verified success or implement a durable, atomic idempotency record checked before any remote write.
5. Success claims require evidence from the job log or target-system API; merge success alone is insufficient.
6. Duplicate remote writes must be prevented by target-side idempotency where available, otherwise by preflight identity lookup and explicit conflict handling.

## Abuse cases and bypass tests

- Push with exact trigger text after the intended operation -> no workflow exists, therefore no write.
- Squash commit adds a body -> authorization must not depend on string equality.
- Re-run or replay of a successful job -> denied by idempotency/preflight check.
- Missing or invalid secrets -> fail closed.
- Unexpected input file, traversal, or shell payload -> rejected by ADR-0010 controls.
- Valid reviewed manual dispatch with `apply=false` -> validation only.
- Valid reviewed manual dispatch with `apply=true` -> one bounded upload attempt with auditable result.

## Verification

Positive:
- Existing Zotero dry-run workflow accepts the approved JSON file and reports `applied=false`.

Negative:
- Repository tree contains no push-triggered workflow with Zotero write secrets.
- Missing secrets, invalid paths, invalid collection keys, and unsupported metadata fail closed.

Bypass:
- Commit title/body variants cannot authorize an external write.
- Replaying the former trigger text cannot execute anything.

CI gate:
- Full repository tests and NEXUS build verification must pass.
- Security review confirms no unresolved thread and re-reads the final head SHA before merge.

## Rollback, recovery, and incident handling

Rollback of this decision would reintroduce the persistent trigger and is prohibited without a superseding accepted ADR and equivalent or stronger controls.

Recovery for the failed intended upload: use the existing manual Zotero workflow after dry-run, with explicit `apply=true`; verify the Zotero API result or target library before reporting completion.

If logs show an unexpected write or possible secret disclosure, disable affected workflows, preserve non-sensitive logs, revoke/rotate the Zotero API key, inspect target-library changes, remove duplicate or unauthorized items, and document the incident.

## Residual risk

Repository administrators can still modify workflows or secrets. Branch protection, review requirements, secret scoping, target-side audit logs, and eventual workload identity remain necessary. The current Zotero API integration uses a static API key, so credential lifetime is broader than an ephemeral federated identity.

## Confidence

**High** for removing the recurrent trigger and eliminating this exact replay path. **Medium** for the broader write workflow until idempotency and target-side verification are implemented.

## References

- NIST SP 800-53 Rev. 5, AC-6 and SI-7.
- GitHub Docs, Security hardening for GitHub Actions.
- Koishybayev et al., Characterizing the Security of GitHub CI Workflows, USENIX Security 2022.
- Codecov, Post-Mortem / Root Cause Analysis, April 2021.
