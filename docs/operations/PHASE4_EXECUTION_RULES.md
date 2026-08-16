# NEXUS Phase 4 Execution Rules

Parent contract: #510

These rules are normative for Phase 4 execution and are intended to prevent idle time, forgotten infrastructure, and PR/evidence loops.

## 1. Full-resource utilization is default
NEXUS must actively use all already-approved execution resources when they are relevant and available, without waiting for repeated owner reminders:
- specialist agents;
- DeepSeek / bounded auxiliary models;
- GitHub Actions;
- cloud fallback;
- the Windows self-hosted laptop runner;
- parallel test/research/audit paths that do not violate file/state ownership boundaries.

Idle resources are treated as an execution inefficiency unless blocked by authority, dependency, safety, or availability constraints.

## 2. Five-minute error rule
Any active Phase 4 job, check, agent task, runner task, or provider task that is failed, blocked, unexpectedly idle, or materially stalled must enter triage within five minutes of detection.

Triage sequence:
1. identify whether the state is real failure, queue delay, external dependency, stale evidence, or expected wait;
2. collect the smallest useful logs/evidence;
3. assign root-cause class and owner;
4. if a real defect exists, repair the existing branch/PR/task path where safe;
5. rerun only the minimum required validation first, then the full required gate set;
6. record durable evidence and continue automatically.

Do not leave failed or blocked work waiting for manual prompting when the system already has enough authority and context to proceed.

## 3. No artificial PR loops
- Real code/schema/policy/config defect -> change allowed in the current appropriate PR/branch, or a new PR only when separation is architecturally required.
- Evidence-only, rerun-only, status bookkeeping, verification, or closure -> no new PR.
- Do not create a fresh PR merely because previous evidence is old.

## 4. Parallelism by default
Independent work should run concurrently when it does not create merge, state, authority, or evidence ambiguity.
Examples: UI shell design, data audit, event-contract audit, negative-test generation, log analysis, documentation, and bounded research validation.

## 5. Authority boundaries remain unchanged
Fast execution does not permit bypassing deterministic risk, security, privacy, paper/live air-gap, merge, signing, billing, production, credential, or owner-required gates.

## 6. Escalation threshold
Owner intervention is required only when:
- an L4/owner-required action is reached;
- credentials, billing, signing, production, or irreversible authority is required;
- two plausible recovery paths have materially different risk/architecture consequences;
- a blocker cannot be resolved with current tools/permissions;
- frozen Phase 4 scope would need to change.

## 7. Operational status discipline
Every material task should move through an explicit state such as QUEUED -> RUNNING -> WAITING/BLOCKED -> DONE/FAILED. Stale WAITING/BLOCKED states must be re-evaluated under the five-minute error rule.

## 8. Evidence discipline
Every repair must bind to the exact revision/job/run used to prove recovery. A fix is not complete until the relevant required checks pass on the exact resulting revision.

These rules apply throughout Phase 4 unless explicitly superseded by a stricter frozen gate in #510.