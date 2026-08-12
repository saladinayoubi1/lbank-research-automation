# Phase 3 Stabilization and Consolidation Gate

Status: ACTIVE / SCOPE FROZEN

## Objective
Close Phase 3 by proving the existing NEXUS autonomous runtime works end-to-end without expanding feature scope.

## Frozen runtime chain

`GitHub/Issue -> Orchestrator -> durable queue/state -> Runner/Workers -> DeepSeek advisory worker -> Test/Recovery -> CI evidence -> next task`

## In-scope completion gates

1. **Local Runner bootstrap and resume**
   - self-hosted runner can accept a job after Windows/laptop resume;
   - bootstrap does not depend on unsupported curl flags or destructive re-download on every run;
   - a real post-fix runner execution reaches the functional steps beyond bootstrap.

2. **Durable autonomous continuation**
   - orchestration state survives process restart;
   - queue/task selection does not silently reset to the same oldest work;
   - ambiguous/corrupt state fails closed with an explicit reason.

3. **Bounded DeepSeek worker path**
   - DeepSeek is advisory only;
   - hard monthly budget and reservation/reconciliation rules remain enforced;
   - bounded parallel workloads may include log analysis, test review, edge-case discovery, documentation, and patch proposals;
   - missing key, ambiguous spend, or provider failure must not block the rest of NEXUS.

4. **Control-plane independence**
   - candidate changes cannot silently weaken the policy, validator, workflow, registry, and their tests together and still authorize themselves;
   - recovery restores the previous-valid control tuple.

5. **Project Memory / state continuity**
   - canonical state is fresh enough to resume safely;
   - stale/conflicting state cannot authorize stronger autonomous action;
   - current repository evidence wins over stale memory.

6. **Exact verification**
   - relevant final-head CI is green;
   - unresolved review threads are zero;
   - at least one real local-runner execution verifies the repaired runtime chain through the intended bounded stages;
   - no live trading, production, signing, billing change, or secret disclosure is introduced.

## Blocker classification
A newly discovered issue may block Phase 3 only when it invalidates one of the six gates above. Otherwise classify it as technical debt/next phase or optional and do not extend the Phase 3 deadline.

Current examples:
- #230 is in scope because durable restart/recovery is a frozen runtime requirement.
- #232 is in scope only to the extent needed for bounded DeepSeek worker routing and budget-safe operation.
- #283 is in scope only to the extent stale memory can break autonomous resume.
- #106 is in scope only to the extent candidate changes could self-authorize a weaker runtime/control plane.
- #380 / related CI failures are in scope because Local Runner bootstrap/resume is a frozen runtime requirement.
- unrelated production-release, dashboard-security, strategy-feature, or future hardening issues do not block Phase 3 unless they directly invalidate one of the six gates.

## Consolidation rules
- No new Phase 3 features.
- No replacement PR solely because `main` moved on unrelated paths.
- No new blocker without a cited frozen gate.
- Prefer fixing shared root causes over symptom-specific patches.
- Parallelize independent safe work across CI, Local Runner, DeepSeek advisory analysis, and repository agents.
- Do not wait for owner prompts between safe execution/test/fix cycles.

## Exit condition
Phase 3 is DONE only when all six frozen gates are verified with durable evidence on compatible final revisions. After that, remaining unrelated open issues move to the next-phase backlog and must not retroactively reopen Phase 3 without evidence that a frozen gate was false-green.
