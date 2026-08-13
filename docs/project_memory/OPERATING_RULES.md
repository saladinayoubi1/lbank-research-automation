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

## 2. Product Priority
The primary objective is not infrastructure for its own sake. The primary objective is to produce research-backed trading strategies that survive realistic validation and can progress through research -> backtest -> paper-trading evaluation.

Strategy quality and evidence are the product. Infrastructure, CI, memory, governance, agents, runners, and recovery controls exist to support that product, not to become the dominant workload.

Keep Phase 3 foundational crypto evidence work moving in parallel with infrastructure remediation. Do not pause independent strategy/evidence work merely because a non-blocking reliability or governance item remains open.

For each strategy family, prioritize an evidence-to-experiment loop:
1. evidence hypothesis and market rationale;
2. explicit entry/exit/risk rules with no hidden discretion;
3. data requirements and semantic compatibility;
4. deterministic backtest implementation;
5. transaction costs, slippage, funding, latency, leverage/liquidation and execution realism where applicable;
6. train/validation/out-of-sample or walk-forward separation;
7. robustness tests across regimes, symbols, timeframes and parameter perturbations;
8. benchmark comparison and statistical uncertainty;
9. failure modes, invalidation criteria and kill conditions;
10. paper-trading eligibility only after the above is verified.

Do not optimize primarily for headline return. Prefer repeatable risk-adjusted performance, drawdown control, stability, implementation realism, low leakage/overfitting risk, and reproducible evidence.

A governance/reliability task may block a strategy experiment only when it can materially invalidate the experiment's data, execution assumptions, reproducibility, safety boundary, or measured result. Otherwise run both tracks in parallel.

## 3. Phase Execution Architecture
During an active phase, work is split into three explicit lanes:

- **Lane P — Product/Research:** phase deliverables, evidence packs, strategy hypotheses, deterministic backtests and paper-trading readiness. This lane receives at least 50% of execution capacity whenever it has executable work.
- **Lane B — Frozen Blockers:** only blockers already mapped to frozen phase exit gates. This lane may remediate root causes but may not expand the phase acceptance contract.
- **Lane Q — Quarantine/Backlog:** newly discovered hardening, release, security, supply-chain, governance, DR, CI and architecture improvements that do not directly invalidate a frozen exit gate. Record them once and defer them; do not recursively analyze them during the active phase.

WIP limits during stabilization:
- at most 2 active technical blocker PRs at once;
- at most 1 continuity/memory PR at once, and normally none unless a material event requires it;
- every active blocker PR must name the exact frozen exit gate it closes;
- if a blocker generates a newly discovered concern outside that gate, route that concern to Lane Q instead of expanding the PR;
- after two consecutive remediation iterations on the same blocker without closing its acceptance criterion, perform root-cause consolidation before another patch;
- when blocker work waits on CI, runner, review, or external availability, Lane P must continue rather than idling.

A phase cannot be held open by an unbounded chain of newly discovered controls. New findings may override the freeze only when they demonstrate a concrete high-impact failure that makes a frozen acceptance claim false or unsafe. The override must identify the exact invalidated claim; otherwise it is next-phase backlog.

## 4. Execution Efficiency
Prefer material reduction of real blockers and product milestones over continuity/admin churn.
Do not create repeated Project Memory refresh PRs for trivial main movement.
Update continuity after material events, not every small repository change.
If one task is waiting on CI/review, move to another independent high-value blocker or strategy/evidence task instead of spinning.
Use GitHub Actions, agents, cloud fallback, DeepSeek, Zotero, and the laptop/self-hosted runner only where they materially improve speed, quality, verification, research throughput, or resilience.

### Main-drift / replay control
Do not automatically close and replay a technical PR merely because `main` advanced.
First classify the drift:
- **incidental drift**: unrelated public market-data/candle refreshes, continuity-only changes, or other non-overlapping changes that do not alter the PR's assumptions, touched code, tests, policy, authority, or acceptance criteria;
- **material drift**: overlapping code/policy/schema/workflow/test changes, changed assumptions, changed authority, or anything that can invalidate the PR's evidence.

For incidental drift, preserve the existing PR whenever possible. Compare the changed paths/semantics, update or rebase the branch only when technically required, and rerun the minimum exact-head verification needed. Incidental drift alone is not a reason to create a replacement PR.
For material drift, re-establish evidence on the new base before merge; replay only when preserving the existing PR cannot safely establish the new evidence.
Do not make volatile exact-`main` SHA equality a completion requirement for continuity-only snapshots unless the snapshot is specifically proving a material fixed-SHA property.
Prefer semantic applicability and non-overlap checks over churn caused solely by unrelated data refresh commits.
Track replay rate as an efficiency signal: repeated replacement PRs caused by incidental drift are an operational defect to reduce, not normal progress.

## 5. Continuity Across Chats
Chat is a temporary working interface, not the source of truth.
GitHub + Project Memory are the durable source of truth.
A new chat must recover current state from durable project memory and current GitHub evidence rather than asking the owner to restate old decisions.
Do not assume a previous chat's claim is authoritative when current repository evidence disagrees.

## 6. Authority Boundary
NEXUS remains research/backtest/paper-only unless the owner explicitly changes the project authority in a separately verified decision.
No live trading, production authority, credential disclosure, signing authority, billing changes, secret disclosure, or irreversible actions.
Risky or ambiguous changes must not be merged automatically.

## 7. Owner Experience
The owner should not need to repeatedly ask whether a task was tested, whether continuity was saved, whether a blocker actually moved, or whether research work is being displaced by infrastructure work.
Surface only meaningful milestones, real blockers, failed/missing verification, material efficiency problems, stale assumptions, strategy/evidence milestones, or actions that require owner involvement.
Mark owner-required actions with 🔴.

## 8. Phase Scope Freeze and Blocker Classification
Once a phase enters stabilization, its Definition of Done is frozen. A newly discovered failure must be classified before it can expand the phase:
- **phase blocker**: directly prevents an already-declared phase acceptance criterion from being met;
- **technical debt / next phase**: real defect or hardening opportunity that does not invalidate the frozen phase acceptance criteria;
- **non-blocking / optional**: useful improvement that must not delay phase closure.

Only a phase blocker may delay phase closure. Do not silently promote new hardening ideas, new governance requirements, or unrelated CI improvements into the active phase. Any exception must explicitly identify which frozen acceptance criterion is invalidated.

For Phase 3 specifically, no new feature scope is allowed. The active stabilization objective is limited to closing the already-open autonomous-runtime and reliability acceptance boundaries that prevent verified end-to-end operation. New feature requests, speculative hardening, release-readiness, production signing, full DR, broad supply-chain hardening and unrelated infrastructure improvements go to Lane Q unless they directly falsify a frozen Phase 3 exit gate.

## 9. Consolidation-First Engineering
Do not treat closely coupled autonomy failures as separate patch streams when they form one runtime chain. Diagnose and verify the whole chain:

`GitHub/Issue -> Orchestrator -> durable queue/state -> Runner/Workers -> DeepSeek advisory worker -> Test/Recovery -> CI evidence -> next task`

For this chain:
1. prefer one stabilization plan and one bounded acceptance matrix over repeated local fixes;
2. reuse existing components instead of adding parallel mechanisms unless replacement is explicitly justified;
3. require restart/recovery evidence across the chain, not only isolated unit success;
4. prevent CI/policy/test changes from self-authorizing weaker acceptance;
5. when one worker is blocked, schedule another independent safe task instead of idling;
6. use DeepSeek for bounded parallel analysis, test review, edge-case discovery, log analysis, and patch proposals when budget and secret gates permit;
7. keep merge/release/risk authority deterministic and outside DeepSeek.

A patch that fixes one symptom but leaves the same end-to-end failure mode untested is not considered stabilization complete. Conversely, once the frozen end-to-end acceptance claim is proven, additional hardening is not allowed to reopen the phase unless it demonstrates that claim is actually false or unsafe.

## 10. Execution Intent and No-Reinterpretation Rule
When the owner gives a clear operational instruction, execute the requested operation as stated unless doing so is technically impossible, unsafe, irreversible, or requires missing authority. Do not substitute a different project, broaden the requested scope, or reinterpret a direct execution request into planning-only work merely for convenience.

If an exact request cannot be executed, state the concrete limitation once, then perform the closest safe action that advances the same objective. Avoid repeated clarification when current repository state can resolve ambiguity.

For project work, default to: inspect current evidence -> execute bounded safe work -> verify -> continue to the next independent safe task. Do not stop merely to ask for another "continue", "test", or "run" instruction when no owner decision is required.
