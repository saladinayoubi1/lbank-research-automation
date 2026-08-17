# ADR-AI-PROVIDER-BUDGET — Bounded paid AI provider authority

Status: accepted for research-assistance only

## Decision

NEXUS treats paid AI-provider routing as an optional, deny-by-default capability. The only current paid provider implementation is `deepseek_provider.py`; no parallel ledger or alternate paid path is authoritative.

The monthly DeepSeek authorization ceiling is USD 5.00. Routine work cannot consume the final USD 0.50 reserve. A provider request is not authorized by key presence alone: the explicit paid-routing gate, provider policy, canonical ledger, current pricing version, conservative reservation and network-egress authorization must all succeed before application bytes are sent.

## Authority

The budget owner may lower or disable the cap, but candidate code cannot increase spend authority, change billing, add live-trading authority, or silently substitute a provider/model. Deterministic Risk remains final authority for paper trading. AI output is advisory only.

Canonical ledger: `build/deepseek/usage.json`.

An alternate ledger path is rejected. Missing ledger after prior initialization, malformed accounting, stale schema/pricing, unknown model, inconsistent usage, unresolved month rollover or a cap violation all fail closed.

## Pricing and reservation

Pricing is versioned in `deepseek_provider.PRICING_VERSION` and `PRICING`. Before provider I/O, NEXUS reserves a conservative cache-miss input bound plus the complete configured maximum output. Reservation ownership is persisted under a kernel-managed exclusive lock. The committed amount is `spent_usd + reserved_usd`; it may never exceed the monthly cap.

Routine requests are evaluated against `MONTHLY_BUDGET_USD - RESERVE_USD`. Explicit blocker-class work may consume the reserve but still cannot cross the monthly cap.

## Request lifecycle

1. Validate secret presence and egress content policy.
2. Resolve an allowed model and current pricing version.
3. Authorize the exact HTTPS destination.
4. Acquire the canonical ledger lock.
5. Validate ledger integrity and atomically persist a unique inflight reservation.
6. Only then perform provider I/O.
7. Reconcile provider usage against that reservation.
8. If reconciliation is unambiguous and actual cost is within the reservation, commit actual spend and release the reservation.
9. For timeout, transport failure, missing/malformed usage, cost above reservation, or any other ambiguous outcome, retain/quarantine the reservation. Do not refund it automatically and do not retry against the same budget slice.

## Threat and abuse cases

The control must withstand: large input with small output; cache hit/miss mismatch; two workers racing the final slice; timeout after provider acceptance; retry double spend; malformed or missing usage counters; negative/inconsistent counters; ledger deletion/truncation/tamper; month rollover with inflight work; stale pricing; model substitution; alternate ledger paths; reserve consumption by routine work; prompt/tool-loop amplification; abrupt process death while holding the coordination lock; and simultaneous weakening of policy plus tests.

The conservative response to every unresolved accounting state is paid-routing denial, not optimistic repair.

## Recovery and provider-observable reconciliation

Recovery never reconstructs spend from memory or silently clears inflight reservations.

- If local ledger and durable initialization state validate and there is no inflight reservation, normal bounded routing may resume.
- If the ledger is missing after initialization, malformed, over-cap, stale, or internally inconsistent, paid routing stays disabled until an operator restores a known-good durable ledger and verifies it.
- If an inflight reservation has a definite provider usage record, reconcile that exact request identity and usage under the canonical lock before routing resumes.
- If provider-observable usage is unavailable or cannot be bound to the exact request, the charge remains ambiguous. Keep the reservation quarantined. Do not assume zero cost. Paid routing may remain disabled for the affected budget slice through month close.
- At month rollover, unresolved inflight work blocks automatic reset. It must first be reconciled or carried as unresolved authority; deletion is not reconciliation.

This means Phase 6 does not require a paid smoke call to establish the control. A future explicitly authorized smoke is reachability evidence, not permission to weaken the ledger contract.

## Rollback

Rollback is a tuple: provider code, pricing table/version, ledger schema, paid-routing gate, network policy, this ADR, and their tests. Preserve ledger and audit evidence during rollback. The safe fallback is paid routing disabled.

## Recovery acceptance

Acceptance requires deterministic offline tests for: final-slice concurrency, ambiguous timeout retention, orphan-lock process exit, tamper/missing-ledger failure, stale pricing/model rejection, reserve denial, month-rollover blocking, malformed usage, alternate ledger path denial and exact reconciliation. Cross-platform CI must run the repository test suite. No paid provider call is required to prove these invariants.

## Obsolescence triggers

Re-review this ADR when provider models/pricing/context limits, cache accounting, usage schema, ledger backend/concurrency, retry/fallback architecture, tool-loop capability, budget/reserve policy, secret storage, network-egress architecture, or billing observability changes.

## Residual risk

Provider billing can remain temporarily unobservable after ambiguous network outcomes. NEXUS resolves that uncertainty by withholding authority (reservation quarantine / paid-routing denial), not by claiming exact provider-side spend. The USD 5.00 claim is therefore an authorization bound under the documented conservative accounting model, not a promise that an external provider can never misbill independently of NEXUS.
