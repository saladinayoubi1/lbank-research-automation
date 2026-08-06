# ADR-0017: Continuous regression, mutation, and bypass verification

- Status: Proposed
- Version: 1
- Scope: GitHub Actions workflow permission checker, policy, and focused tests
- Supersedes: none; extends ADR-0016

## Context

ADR-0016 introduced a fail-closed workflow and job permission inventory. A static control can regress when parser behavior, permission scopes, policy structure, workflow inventory, or maintenance code changes. Tests must prove both acceptance of reviewed read-only configurations and rejection of adversarial or mutated configurations without weakening the existing gate.

## Decision

Maintain a focused suite with four classes of evidence:

1. Positive regression tests for reviewed workflow-level and job-level read-only permissions, including inline mappings.
2. Negative tests for malformed YAML, duplicate keys, anchors, aliases, scalar permissions, empty permission maps, invalid levels, and unknown scopes.
3. Mutation tests for policy version changes, workflow/job policy-version drift, permission mutations, blank write justifications, duplicate JSON keys, and unexpected policy fields.
4. Bypass tests for `write-all`, `read-all`, undocumented writes, job widening, new or stale workflows, and new or removed jobs.

The checker must continue to audit the complete `.github/workflows` inventory. Permission scopes are explicitly enumerated; an unknown future scope fails closed until reviewed and added. Policy JSON is loaded with duplicate-key rejection. Policy, workflow, and job rule schemas reject unexpected fields.

## Threat model

Threat actors include malicious contributors, compromised automation, and maintainers making unsafe policy edits. Relevant attacks include parser differential behavior, duplicate-key shadowing, scalar shortcuts, policy self-authorization, blank justifications, inventory drift, job escalation, and mutation of versioned controls.

The control trusts the pinned parser, repository checkout, CI runner, committed policy, and branch protection. It does not establish the integrity of third-party actions or external reusable workflows.

## Regression safety

Existing ADR-0016 checks remain mandatory. A test addition must not convert a prior rejection into acceptance. Checker changes require the complete focused suite and repository CI on one fixed head SHA. Shared workflows are not modified by this ADR.

## Rollback

Revert the commits for Issue #82 or close its Draft PR. Do not edit `main` directly and do not disable the ADR-0016 gate. If a checker regression is discovered after merge, revert to the previous-valid checker and test suite while preserving the committed workflow policy.

## Recovery

Restore the previous-valid checker, policy, and focused tests from Git history; rerun the complete workflow inventory audit and all regression, mutation, and bypass tests; then repair the rejected mutation in an independent branch and Draft PR. Promotion requires green CI on a fixed head SHA and zero unresolved review threads.

## Residual risk

A maintainer able to modify checker, policy, tests, and branch protections may create internally consistent malicious changes. The suite cannot prove third-party action integrity, external reusable workflow behavior, organization-level permission defaults, non-`GITHUB_TOKEN` credentials, or semantic necessity of a documented write permission.

## Obsolescence triggers

Revisit this ADR when GitHub adds or removes permission scopes, changes effective-permission semantics, PyYAML parsing behavior changes, workflow generation is introduced, external reusable workflows are modeled, or a maintained typed policy engine replaces this checker.
