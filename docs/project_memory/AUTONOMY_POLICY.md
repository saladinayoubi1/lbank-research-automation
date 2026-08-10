# NEXUS Autonomous Execution Policy

## Standing owner instruction

For all virtual/software project work, the agent should proceed autonomously without waiting for repeated owner commands such as “run”, “test”, “continue”, or “do it”.

The agent should:
- execute reversible, low-risk project actions when they are the natural next step;
- run relevant tests and validations automatically;
- diagnose failures and apply safe fixes when possible;
- continue iterating until the task is complete, a verified external dependency blocks progress, or an action crosses a protected boundary;
- avoid stopping merely because an intermediate step succeeded;
- batch independent or sequentially compatible safe actions together and execute them back-to-back whenever practical;
- avoid artificial waiting periods, one-action-per-hour pacing, or unnecessary pauses between code changes, tests, fixes, validation, and follow-up checks;
- prefer one cohesive execution pass that includes implementation, tests, diagnostics, safe repairs, re-tests, and verification instead of requiring repeated owner prompts;
- use parallel execution only when actions are truly independent and cannot race on the same file, branch, state, or external resource;
- surface owner intervention only when genuinely required, and mark it with 🔴.

Protected boundaries still require explicit owner approval or owner-side action when applicable, including irreversible/high-impact operations, production deployment or production authority, live trading or financial/risk-policy changes, billing changes beyond an already approved hard cap, credential/secret entry, destructive data operations, or permissions the agent does not actually possess.

This policy does not authorize bypassing tests, security controls, budget guards, provenance rules, or fail-closed safety gates.
