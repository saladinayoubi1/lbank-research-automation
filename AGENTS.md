# NEXUS Agent Operating Rules

## Time-efficiency rule

- Do not leave work idle just because an interactive assistant/session ends before a previously expected time window.
- Prefer repository-native continuation: GitHub Actions, self-hosted runner jobs, scheduled/push-triggered workflows, durable artifacts, commits, issues, and resumable checkpoints.
- If a task can safely continue without user input, arrange it to continue automatically instead of waiting for the user or an arbitrary time window.
- Split long work into bounded, resumable stages with explicit checkpoints so a later run resumes from the latest completed state rather than starting over.
- Avoid duplicate work: inspect the latest commit, workflow result, artifact, and status file before rerunning expensive steps.
- Ask for user intervention only when a real external dependency requires it (Windows/local device action, account approval, 2FA, unavailable connector capability, or a safety-sensitive decision).
- Surface any user-blocking or intervention-required condition with 🔴 in reports.

## Scoped-blocking rule

- Treat a security, policy, permission, runner, or external-dependency denial as local to the exact blocked operation unless repository evidence explicitly proves a wider boundary.
- Never generalize one denied operation into claims such as "GitHub access is unavailable", "no repository changes are possible", or "the project cannot continue" when other repository actions remain available.
- Before reporting an access limitation, distinguish these states explicitly: connector/tool unavailable, repository permission denied, protected-path/policy denial, required human approval, unavailable physical runner, or task-specific fail-closed result.
- When one operation is blocked, record the exact operation and reason, mark it 🔴 only if user intervention is actually required, then immediately continue every independent safe task that remains executable.
- Protected or frozen control-plane paths remain protected. This rule does not weaken security gates, bypass break-glass requirements, expand credentials, or grant Live/L4/production authority.

## Anti-report-loop rule

- Reporting is never a substitute for execution. After reporting a blocker or status, continue with the next executable task in the same run whenever one exists.
- Do not repeat substantially identical status reports unless repository state changed, a new fact was discovered, or the user explicitly requested another report.
- After two consecutive attempts that produce no repository-state change, stop retrying the same operation. Reclassify the blocker, choose a different safe task, or surface one concise 🔴 intervention item if no independent work remains.
- Do not restart analysis from the beginning after a scoped failure. Resume from the latest verified commit, workflow run, artifact, issue, PR, or checkpoint.
- A session must not enter a read-only/report-only mode merely because one mutation failed. Re-evaluate actual available connector capabilities and continue with permitted mutations or verification work.

## Capability-truth rule

- Repository/tool capability claims must be based on an actual connector/tool result from the current session when that capability is available to test.
- If GitHub reads or writes succeed in the current session, do not claim that GitHub is disconnected or inaccessible.
- If a write fails, report the concrete failed action and returned boundary; do not infer that unrelated write actions will also fail without evidence.
- User approval and technical capability are separate concepts: existing user approval does not bypass protected governance, and protected governance does not imply loss of ordinary repository access.
