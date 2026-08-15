# NEXUS Phase 4 Contract

Status: FROZEN DRAFT for Gate 0/1 review
Parent: #510
Base main: `e8537213eded35c685b78801174f1d688a0acd0b`

## Mission
Build a deterministic, recoverable, auditable paper-trading platform with an AI operations console. Phase 4 authorizes paper/demo behavior only. It does not authorize live orders, exchange credentials, withdrawals, production promotion/deployment, signing, billing changes, or irreversible financial action.

## End-to-end authority chain
`Validated Market Data -> Research Qualification -> Strategy/Regime -> Decision -> Deterministic Risk -> Paper Execution -> Append-Only Event Store -> Portfolio/Accounting -> Dashboard/API`

AI control path:
`AI Chat Room -> Intent/Classify -> Context/Memory -> Agent/Tool Router -> Proposed Action -> Authority/Policy Gate -> Deterministic Validator -> Allowed Tool/Command -> Audit/Event -> Durable Memory Update`

## Non-negotiable authority rules
1. Deterministic validators and the Risk Engine retain final authority over paper execution.
2. AI, agents, UI, strategies and external providers may propose actions but cannot bypass deterministic validation or self-promote authority.
3. UI never mutates portfolio/event state directly; all writes use the same validated command path as automation.
4. Chat history is not authoritative project state. Durable state belongs in versioned Project Memory/STATE/decision records and deterministic event/config stores.
5. Ambiguous, stale, malformed, conflicting or unverifiable state fails closed and preserves the previous-valid state.
6. No silent fallback across data source, model/provider, strategy, risk policy or execution mode.
7. No synthetic/interpolated candles may be created to satisfy continuity.
8. Persisted/public contracts are versioned and require compatibility/migration notes.

## Phase 4 blocker rule
An existing or new issue blocks Phase 4 only when current evidence identifies the exact frozen Gate it invalidates. Production-release, signing, credential, real-money, billing and unrelated backlog work remains outside this phase.

## PR / evidence anti-loop rule
- A demonstrated code/schema/policy defect requiring a real change may produce a PR.
- Evidence-only reruns, verification, status bookkeeping, issue closure or documentation of already-present facts do not justify a new PR.
- Once a final SHA is selected, a new PR requires a newly demonstrated defect that invalidates a frozen Gate.

## Change-control rule
Every high-impact change must declare: owner/module, input/output contract, authority effect, persisted-schema effect, tests, observability, rollback, recovery, residual risk and obsolescence triggers.

## Definition of Done
A slice is not done until all applicable conditions hold on one fixed head SHA:
- required unit/contract/integration/adversarial/replay/recovery/concurrency/UI tests are green;
- regression coverage exists for every bug fix;
- module/API/schema contracts are aligned;
- observability and deterministic reason codes exist;
- rollback and previous-valid recovery are documented/tested where state changes;
- no unresolved review thread remains;
- no unsupported live/production/credential/billing/signing authority is introduced.

## Frozen Gate sequence
0. Scope and authority contract
1. Architecture and module contracts
2. UI/UX site shell and versioned API surface
3. Canonical data authority
4. Research qualification
5. Deterministic domain model and append-only event store
6. Versioned config and registries
7. Deterministic Risk Engine
8. Paper execution and accounting
9. Automated signal pipeline
10. AI Chat Room and AI Control Plane
11. Multi-agent / auxiliary-provider boundaries
12. Project Memory and chat migration
13. Mission queue, operations and notifications
14. Dashboard security/access boundary
15. Observability and auditability
16. Failure taxonomy, concurrency and idempotency
17. Recovery and chaos matrix
18. Security/privacy and paper/live air gap
19. Performance/resource bounds
20. Full E2E and final evidence freeze

Gate numbering and authority semantics are frozen by #510. Implementation details may evolve only without weakening a Gate or expanding Phase authority.

## Exit condition
Phase 4 closes only when one fixed final revision proves the full paper path from validated data through qualified strategy, deterministic decision/risk, paper execution/accounting, dashboard/audit and restart/replay with identical previous-valid state, while the AI Chat Room can inspect/orchestrate within bounded authority and cannot assume deterministic risk/execution authority.
