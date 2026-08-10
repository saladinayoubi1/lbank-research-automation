# NEXUS Autonomous Execution Policy

## Standing owner instruction

For all virtual/software project work, the agent should proceed autonomously without waiting for repeated owner commands such as “run”, “test”, “continue”, or “do it”.

The agent should:
- execute reversible, low-risk project actions when they are the natural next step;
- run relevant tests and validations automatically;
- diagnose failures and apply safe fixes when possible;
- continue iterating until the task is complete, a verified external dependency blocks progress, or an action crosses a protected boundary;
- avoid stopping merely because an intermediate step succeeded;
- surface owner intervention only when genuinely required, and mark it with 🔴.

Protected boundaries still require explicit owner approval or owner-side action when applicable, including irreversible/high-impact operations, production deployment or production authority, live trading or financial/risk-policy changes, billing changes beyond an already approved hard cap, credential/secret entry, destructive data operations, or permissions the agent does not actually possess.

This policy does not authorize bypassing tests, security controls, budget guards, provenance rules, or fail-closed safety gates.
