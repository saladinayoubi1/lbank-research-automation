# NEXUS Continuity & Recovery Playbook

## Fresh-session bootstrap
1. Read `PROJECT_MEMORY.md`.
2. Parse `STATE.json`.
3. Read the newest entries in `DECISIONS.md`.
4. Read this playbook.
5. Verify current `main`, open PRs/issues and CI/workflow evidence before assuming recorded transient state is still current.
6. Resume only work consistent with the mission and authority boundary.

## If chat history disappears
Do not reconstruct from guesses. Recover from repository memory, git history, issues/PRs, workflow artifacts/status and approved external archives. Record any unresolved ambiguity as a blocker rather than inventing context.

## If laptop is offline
Treat the local supervisor as unavailable, not as an internet outage. Cloud workflows/fallback should continue where configured. Do not infer that GitHub/cloud is down merely because the local node stopped reporting.

## If internet is unavailable but laptop remains on
Local state may continue, but remote status is stale. Queue safe work where supported; do not claim remote success until connectivity returns and evidence is verified.

## If an agent/workflow fails
1. Capture failure evidence.
2. Classify: transient infrastructure, deterministic code/test, permission/security, data-integrity, or unknown.
3. Retry only within the reviewed retry budget and only for reversible operations.
4. Never weaken integrity/security gates to convert failure into success.
5. If a repair succeeds, record the failure signature and validated repair so the same problem can be handled faster next time.
6. Escalate when retry budget is exhausted, evidence conflicts, required authority is missing, or action would be destructive/high-impact.

## If memory itself is stale or inconsistent
Repository/runtime evidence wins for transient facts. Core mission/safety changes require human approval. Record supersession rather than deleting old decisions.

## Backup principle
Keep at least two independent durable copies of essential project knowledge: repository history plus an external archive/backup. Backup presence alone is not recovery evidence; verify freshness, source identity, integrity, and content binding before treating a backup as authoritative. Backups must exclude secrets and should include hashes/manifests where practical.

## WSL exact-source and artifact transport recovery
- Do not run JavaScript actions on the WSL1 physical runner; package/upload artifacts only on a compatible hosted runner.
- Do not repair WSL Git fetch timeouts with unbounded retries. Package the exact commit on hosted, bind it to the current run/main SHA, and verify the GitHub outer digest, inner archive digest, commit marker, member types, paths and size bounds before extraction.
- Retain one verified exact-source root across same-run Discovery, runtime snapshot and requalification. Clean it on failure and after the final physical consumer.
- For the locked runtime wheelhouse, a persistent cache is only a hint. Reject symlinks; deterministically repack it; require the exact hosted digest, repository `requirements.lock`, and wheel presence. On any mismatch, delete it and use current-run artifact restore.
- A failed-jobs retry cannot reconstruct an ephemeral same-run chain after cleanup deleted its source/state roots. Prefer a new reviewed architecture fix and a new exact-main run.
- If a physical Paper loop returns `WAITING_FOR_FRESH_CELLS`, require the engine and independent verifier to pass, require `fresh_cell_count < expected_cell_count`, require the waiting mission gap, and require maintenance, regime, rebalance, exposure increase, performance feedback and health-trigger effects to remain inactive. Persist the complete verification-valid waiting state so source-SHA lineage can converge on the next natural candle boundary. Require the full configured fresh-cell count only for `PAPER_LOOP_ACTIVE`; never fabricate cells, relabel waiting as active, infer data or silently substitute exchanges.

## Rotating GitHub replay-artifact recovery
- Never use a fixed GitHub Actions artifact ID as durable replay transport; artifacts expire even when repository history remains valid.
- Select only unexpired artifacts matching the reviewed prefix, then independently require the exact replay filename, delivery manifest, zip payload, embedded manifest, and canonical semantic dataset identity.
- If an operator supplies an artifact ID, use it only to filter the candidate set; all content and semantic checks remain mandatory.
- Treat HTTP 410 for a fixed artifact as evidence to repair transport architecture. Do not blindly replace it with another fixed ID or relax integrity checks.
- A positive Strategy Factory research gate stops at its declared review boundary. Preserve `automatic_paper_forward_started=false` until an independent human review explicitly authorizes the next bounded Research/Paper step; never infer Live or private-credential authority.

## Isolated feedback verifier recovery
- Treat GitHub Actions jobs as isolated execution environments. A dependency installation in a contract job does not provision a downstream feedback job.
- Before importing repository runtime verifiers, provision pinned Python and `requirements.lock` inside the importing job, run `pip check`, and retain regression coverage that enforces this ordering.
- If verifier import fails because a locked dependency is missing, repair provisioning; never bypass or reimplement the verifier merely to make the workflow green.
- After repair, reproduce both evidence producers on one exact current-main SHA and require exact-run artifact identities and GitHub digests before evaluating the boundary.
- A verified `NO_OP_NOT_ELIGIBLE` is complete evidence for a false natural boundary condition. Do not fabricate fresh cells, force eligibility, emit a feedback artifact, or create promotion authority.
