# NEXUS project-state repair — 2026-08-18

## Observed base

- repository: `saladinayoubi1/lbank-research-automation`
- exact observed `main`: `1f33820d88b9dedf8c8641d93d14aaf20d0c1b7b`
- open pull requests at observation: `0`
- open CI triage issues at observation: `134`
- open substantive issues at observation: `13`

## Defects repaired in this candidate

1. `docs/project_memory/STATE.json` was stale at `93c0713b45e2dded424d599b6093c93fac4fc086` and still described PR #505 as draft plus several superseded PRs as open.
2. `.github/workflows/nexus-event-driven-failure-triage.yml` created/upserted one failure issue per workflow+SHA but did not retire records when a PR head advanced, the PR closed/merged, or an exact SHA later passed.
3. The failure-triage lifecycle defect allowed historical CI records to dominate the active issue queue and obscure current actionable work.

## Repair contract

- Keep failure detection fail-closed.
- Keep the exact current head failure open until exact-head success evidence exists.
- Close only CI triage records whose PR is no longer open at that exact head SHA, or whose exact SHA later succeeds.
- On the default branch, a newer run retires older same-workflow default-branch failure records.
- Preserve issue history; closure is auditable and appends a NEXUS CI hygiene reason.
- Do not weaken Test, NEXUS Build Verification, NEXUS Cloud Fallback, workflow permissions, data-integrity gates, deterministic Risk, or the Research/Backtest/Paper-only authority boundary.

## Regression coverage

`tests/test_nexus_event_driven_failure_triage.py` now asserts:

- success events are observed only for cleanup;
- only failure-like conclusions create failure issues;
- exact open PR head SHA controls actionability;
- exact-SHA success closes the matching failure;
- default-branch newer runs retire older same-workflow failures;
- cleanup closes rather than deletes issue history;
- privileged workflow still does not checkout or execute triggering code/artifacts.

## Rollback

Revert this maintenance PR as one tuple. Reversion restores the previous event-driven triage behavior and the prior Project Memory snapshot; it does not grant production, credential, billing, signing, deployment or live-trading authority.
