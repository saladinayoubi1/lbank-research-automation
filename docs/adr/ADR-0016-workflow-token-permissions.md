# ADR-0016: Fail-closed GitHub Actions token permission policy

- Status: Proposed
- Version: 1
- Scope: repository GitHub Actions workflow and job `GITHUB_TOKEN` permissions
- Production readiness: not implied

## Context

Implicit or textually detected permissions do not establish effective least privilege. GitHub computes token authority from repository defaults, workflow permissions, and optional job overrides. YAML duplicate keys, anchors, aliases, scalar shortcuts, malformed documents, and parser-dependent structures can hide or change the interpreted policy.

## Decision

Every `.github/workflows/*.yml` and `.yaml` file must have an exact entry in `security/workflow-permissions-policy-v1.json`. Every workflow and every job is inventoried under a versioned rule. The gate uses PyYAML safe loading with duplicate-key rejection and rejects aliases, anchors, malformed YAML, non-mapping roots, ambiguous scalar permissions, `write-all`, policy drift, undocumented write scopes, and job-level widening.

Unlisted workflows, missing jobs, stale policy entries, and mismatched permissions fail closed. Write scopes require an exact allowlist entry and a non-empty justification. The current policy is expected to prefer `contents: read` and deny other scopes unless separately reviewed.

## Threat model and abuse cases

Threat actors include a compromised action dependency, a malicious or mistaken contributor, and an attacker able to modify workflow YAML. Relevant abuse cases are broad token grants, duplicate-key shadowing, alias-based policy substitution, malformed YAML interpreted differently by tools, inline-map bypasses, job-level escalation, and adding a workflow outside the reviewed inventory.

The trust boundary includes repository workflow files, the committed policy, the parser version installed by CI, and GitHub's effective-permission semantics. External reusable workflows and action implementations are not proven safe by this control.

## Rollback

Rollback is a clean revert of the commits adding the checker, tests, workflow, policy, and this ADR. Closing the draft PR without merge also restores the prior state. Rollback must not weaken `main` directly or bypass review.

## Recovery

When the gate blocks a legitimate workflow, update the versioned policy and workflow together in a reviewed branch. Document every required write scope and job override. If parser or policy corruption occurs, restore the previous-valid committed policy and checker, rerun adversarial tests, and confirm the complete workflow inventory before promotion.

## Residual risk

This gate does not authenticate third-party actions, prove action source integrity, model organization or enterprise permission changes, verify external reusable workflows, prevent credential theft outside `GITHUB_TOKEN`, or guarantee that a justified write scope is operationally safe. A compromised maintainer with permission to modify both policy and workflow can create internally consistent malicious changes; branch protection and independent review remain required.

## Obsolescence triggers

Revisit this ADR when GitHub changes permission semantics, new permission scopes appear, PyYAML security or parsing behavior changes, reusable workflow trust is modeled, repository workflow generation is introduced, or a stronger maintained policy engine replaces this checker.
