# NEXUS Agent Operating Rules

## Time-efficiency rule

- Do not leave work idle just because an interactive assistant/session ends before a previously expected time window.
- Prefer repository-native continuation: GitHub Actions, self-hosted runner jobs, scheduled/push-triggered workflows, durable artifacts, commits, issues, and resumable checkpoints.
- If a task can safely continue without user input, arrange it to continue automatically instead of waiting for the user or an arbitrary time window.
- Split long work into bounded, resumable stages with explicit checkpoints so a later run resumes from the latest completed state rather than starting over.
- Avoid duplicate work: inspect the latest commit, workflow result, artifact, and status file before rerunning expensive steps.
- Ask for user intervention only when a real external dependency requires it (Windows/local device action, account approval, 2FA, unavailable connector capability, or a safety-sensitive decision).
- Surface any user-blocking or intervention-required condition with 🔴 in reports.
