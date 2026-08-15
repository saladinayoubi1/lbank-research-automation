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
