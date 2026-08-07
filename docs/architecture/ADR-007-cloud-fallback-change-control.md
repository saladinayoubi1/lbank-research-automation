# ADR-007: NEXUS cloud-fallback workflow change control

Status: Proposed

## Context

NEXUS uses a cloud-fallback GitHub Actions workflow as an auxiliary recovery/validation path. PR #109 fixes persistent execution gaps in that workflow by adding pull-request and main-push triggers, compiling Python with a valid regex object, installing the locked test environment, failing closed when tests exist without the lock file, running `pip check`, and registering the workflow in the versioned workflow-permissions policy.

A workflow can become a false-green source if it silently changes dependency resolution, skips tests, broadens permissions, diverges from the canonical test environment, or is treated as independent evidence while the same candidate change can weaken both the workflow and its policy inventory.

## Decision

1. The cloud-fallback workflow remains an auxiliary CI/recovery control, not production authorization and not evidence of live-trading readiness.
2. Test dependencies must come from the repository-owned locked development dependency set. If `tests/` exists and that lock is missing, the workflow fails closed.
3. The workflow runs `pip check`, compile validation, and the repository test suite before claiming fallback health.
4. Pull-request and `main` push execution are required so workflow changes are exercised before and after integration. Scheduled/manual execution may remain additive.
5. The workflow must stay registered in the versioned workflow-permissions policy. Permissions must remain least-privilege and explicitly reviewable.
6. Changes to the fallback workflow, its dependency source, permissions inventory, or trust assumptions require fixed-head green CI, mergeability confirmation, zero unresolved review threads, rollback notes, and ADR review when the decision or trust boundary changes.
7. Cloud-fallback success is not independent control-plane evidence while a candidate change can modify both the workflow and the policy/checks that authorize it. Issue #106 remains the governing blocker for stronger self-authorization claims.
8. No workflow, agent, LLM, or auxiliary check may authorize real orders, credentials, billing, production mutation, or risk-policy changes.

## Alternatives considered

### Keep the fallback schedule/manual-only

Rejected because workflow defects can remain latent until recovery is needed and are not exercised on the candidate SHA.

### Install unpinned dependencies ad hoc

Rejected because dependency drift can create non-reproducible results and false greens relative to the canonical test environment.

### Treat the fallback as an independent approval gate

Rejected until an authority outside the candidate change set protects the relevant workflow, validator/policy, and bypass surface. See Issue #106.

## Compatibility

The workflow remains on Python 3.12 and uses the repository's existing locked development dependency set. Trigger additions are additive. This ADR does not change runtime application schemas, market-data contracts, persistence formats, broker/exchange adapters, or execution behavior.

## Threats and failure modes

- missing or modified lock file;
- dependency conflicts hidden by successful installation;
- compile gate disabled or malformed;
- pytest omitted or pointed at a partial test set;
- workflow permissions widened;
- workflow removed from the permissions inventory;
- simultaneous weakening of workflow and its policy/checks;
- stale success from an older head SHA;
- claims that exceed the evidence actually produced by the fallback job.

The workflow must fail closed for missing locked test dependencies when tests are present. Other self-authorization cases remain residual risk until Issue #106 is satisfied.

## Rollback and recovery

Revert the workflow/policy change as one bounded change set and restore the last known-good workflow plus permissions-policy tuple. Run all required repository checks on the rollback SHA before treating fallback health as restored. If dependency or runner behavior changed externally, quarantine the failed fallback result and use the canonical test path while the incompatibility is investigated.

## Observability and evidence

Evidence for a merge decision consists of the exact head SHA, workflow-run conclusions for that SHA, mergeability state, review-thread state, and the reviewed workflow/policy diff. A green result from a different SHA is not acceptable evidence.

## Residual risk

This control does not provide independent control-plane authorization, signed provenance, immutable runner identity, cross-platform fallback execution, production deployment approval, or live-execution safety certification.

## Obsolescence triggers

Revisit this ADR if any of the following change materially:

- Python or runner major version;
- dependency lock format or package manager;
- GitHub Actions permission model;
- workflow trigger architecture;
- required-check/ruleset authority;
- provenance/signing model;
- repository test entrypoint;
- resolution of Issue #106 with a stronger independent authorization mechanism.

## Related work

- PR #109 — cloud-fallback CI gate repair
- Issue #94 — NEXUS architecture baseline and change-control gates
- Issue #106 — independent protection against control-plane self-authorization
