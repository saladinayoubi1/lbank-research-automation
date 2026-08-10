# NEXUS Durable Operating Rules

These rules are durable project operating policy and must survive chat/session changes. Any new execution chat or agent should read this file together with current Project Memory and current GitHub state before claiming continuity.

## 1. Definition of Done
A task, integration, connector, agent action, or repository change is **DONE** only when all of the following are true:
1. implementation/execution is complete;
2. an appropriate real verification/test has run;
3. the observed result matches the acceptance criteria;
4. durable evidence of the verification exists.

Configuration, connection, PR creation, partial workflow execution, or a verbal claim of completion is not DONE.

If verification has not run, classify the work as **UNVERIFIED**.
If verification cannot run, classify it as **BLOCKED**, record the exact reason, and state the next required action.
Never report or persist work as completed without verification evidence.
After executing a task, attempt verification in the same work cycle instead of waiting for the owner to ask later.
Re-check previously claimed completed work whenever evidence is missing, especially external integrations, runners, connectors, automations, Zotero, DeepSeek, and similar dependencies.

## 2. Execution Efficiency
Prefer material reduction of real blockers over continuity/admin churn.
Do not create repeated Project Memory refresh PRs for trivial main movement.
Update continuity after material events, not every small repository change.
If one task is waiting on CI/review, move to another independent high-value blocker instead of spinning.
Use GitHub Actions, agents, cloud fallback, DeepSeek, and the laptop/self-hosted runner only where they materially improve speed, quality, verification, or resilience.

## 3. Continuity Across Chats
Chat is a temporary working interface, not the source of truth.
GitHub + Project Memory are the durable source of truth.
A new chat must recover current state from durable project memory and current GitHub evidence rather than asking the owner to restate old decisions.
Do not assume a previous chat's claim is authoritative when current repository evidence disagrees.

## 4. Authority Boundary
NEXUS remains research/backtest/paper-only unless the owner explicitly changes the project authority in a separately verified decision.
No live trading, production authority, credential disclosure, signing authority, billing changes, secret disclosure, or irreversible actions.
Risky or ambiguous changes must not be merged automatically.

## 5. Owner Experience
The owner should not need to repeatedly ask whether a task was tested, whether continuity was saved, or whether a blocker actually moved.
Surface only meaningful milestones, real blockers, failed/missing verification, material efficiency problems, stale assumptions, or actions that require owner involvement.
Mark owner-required actions with 🔴.
