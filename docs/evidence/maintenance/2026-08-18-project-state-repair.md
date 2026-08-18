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
- Keep the exact current head failure open until exact-head success evidence exists.
- Close only CI triage records whose PR is no longer open at that exact head SHA, or whose exact SHA later succeeds.
- On the default branch, a newer run retires older same-workflow default-branch failure records.
- Preserve issue history; closure is auditable and appends a NEXUS CI hygiene reason.
- Do not weaken Test, NEXUS Build Verification, NEXUS Cloud Fallback, workflow permissions, data-integrity gates, deterministic Risk, or the Research/Backtest/Paper-only authority boundary.

## Regression coverage

`tests/test_nexus_event_driven_failure_triage.py` asserts:

- success events are observed only for cleanup;
- only failure-like conclusions create failure issues;
- exact open PR head SHA controls actionability;
- exact-SHA success closes the matching failure;
- default-branch newer runs retire older same-workflow failures;
- cleanup closes rather than deletes issue history;
- privileged workflow still does not checkout or execute triggering code/artifacts.

## Rollback

Revert this maintenance PR as one tuple. Reversion restores the previous event-driven triage behavior and the prior Project Memory snapshot; it does not grant production, credential, billing, signing, deployment or live-trading authority.
