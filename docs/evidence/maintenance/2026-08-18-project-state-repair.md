# NEXUS project-state repair — 2026-08-18

## Exact repair base

- repository: `saladinayoubi1/lbank-research-automation`
- exact current `main` used for this repair: `c6f7a6ac6adf24b9fb5f35ac10b8623cd63187bf`
- latest integrated change: PR #673 — Windows 4.1.1 Python-sidecar startup hardening
- initial issue-hygiene observation before maintenance PR creation: 134 open CI triage issues and 13 open substantive issues

## Defects repaired in this candidate

1. `docs/project_memory/STATE.json` was stale relative to current `main` and did not include the completed Phase 5/6, canonical Windows/Android product integration, or Windows 4.1.1 hardening.
2. `.github/workflows/nexus-event-driven-failure-triage.yml` created/upserted one failure issue per workflow+SHA but did not retire records when a PR head advanced, the PR closed/merged, or an exact SHA later passed.
3. The missing lifecycle cleanup allowed historical CI records to dominate the active issue queue and obscure current actionable work.

## Repair contract

- Keep failure detection fail-closed.
- Keep an actionable current-head failure open until newer or exact-head evidence supersedes it.
- A newer completed run for the same workflow/event/branch retires the older SHA record.
- An exact-SHA success retires the matching failure record.
- A historical pull-request failure may be retired only after the issue marker is rebound to its recorded Actions run and every PR associated with that run is absent from the current open Issue/PR inventory.
- Missing, malformed, mismatched, unavailable, or association-free historical evidence is preserved rather than guessed closed.
- Preserve the frozen workflow permission tuple: `actions: read`, `contents: read`, `issues: write`; do not add pull-request permission to obtain cleanup capability.
- Preserve issue history; closure is auditable and appends a NEXUS CI hygiene reason.
- Do not weaken Test, NEXUS Build Verification, NEXUS Cloud Fallback, workflow permissions, data-integrity gates, deterministic Risk, or the Research/Backtest/Paper-only authority boundary.

## Regression coverage

`tests/test_nexus_event_driven_failure_triage.py` asserts:

- success events are observed only for cleanup;
- only failure-like conclusions create failure issues;
- the frozen privileged-workflow permission tuple is unchanged;
- a newer same-branch run retires an older SHA without PR-read permission;
- historical cleanup binds marker SHA/workflow/event/run URL to `actions.getWorkflowRun` evidence;
- historical PR closure uses the open Issue/PR inventory and fails closed on missing/mismatched association;
- exact-SHA success and default-branch supersession remain supported;
- cleanup closes rather than deletes issue history;
- privileged workflow still does not checkout or execute triggering code/artifacts.

## Rollback

Revert this maintenance PR as one tuple. Reversion restores the previous event-driven triage behavior and the prior Project Memory snapshot; it does not grant production, credential, billing, signing, deployment or live-trading authority.
