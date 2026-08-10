# ADR-AI-PROVIDER-BUDGET v1

Status: Proposed for validation under issue #232.

## Decision
DeepSeek paid routing is advisory only and is capped at USD $5.00 per UTC calendar month. The repository-owned provider must reserve a conservative worst-case input + output amount before network I/O. No request is sent unless the reservation can be committed atomically to the canonical ledger. Routine work may use at most USD $4.50, preserving USD $0.50 for explicitly blocker/critical work.

## Authority
The project owner controls the monthly cap and provider enablement. DeepSeek has no merge, release, production, credential, billing, live-trading, transfer, withdrawal, destructive-data, permission-escalation, core-goal, or risk-policy authority.

## Billing and pricing identity
Pricing is versioned by `PRICING_VERSION` in `deepseek_provider.py`. Both input and output are charged. Cache-hit and cache-miss accounting are reconciled from provider usage; preflight assumes all possible input is cache-miss at the higher input price. Unknown model, stale pricing, stale ledger schema, malformed usage, or inconsistent counters fail closed.

## Reservation semantics
Before a paid call the provider serializes the bounded prompt, derives a conservative token upper bound from UTF-8 bytes plus protocol headroom, adds the configured maximum output tokens, and reserves worst-case cost. The reservation is written under an exclusive cross-process lock before HTTP I/O. `spent_usd + reserved_usd` may never exceed USD $5.00. Concurrent workers therefore cannot spend the same slice.

## Ledger identity and tamper handling
The production ledger path is fixed at `build/deepseek/usage.json`; alternate paths are rejected by the paid-call path. A companion initialization sentinel detects ledger deletion after first initialization. Malformed, truncated, internally inconsistent, or cap-exceeding ledgers fail closed. Month rollover is permitted only with no unresolved in-flight reservations.

## Timeout, retry, and ambiguity
There is no automatic paid retry after a request is sent. Any network/API/malformed-response ambiguity retains its reservation in the ledger. This quarantines possible billed spend and prevents reuse until reconciliation/recovery. A successful provider response reconciles actual usage against the reservation and releases only the unused portion.

## Fallback
DeepSeek failure must not block NEXUS. Scheduled autonomous orchestration remains repository-queue-only and credential-free; external paid AI is not authoritative for task selection.

## Threat / abuse cases covered
Oversized input with small output; cache accounting mismatch; concurrent last-slice races; timeout after acceptance; retry double-spend; missing/malformed usage; negative/inconsistent counters; ledger deletion/truncation; month rollover with unresolved requests; stale pricing; model substitution; alternate ledger path; routine reserve exhaustion; cost-amplifying planner loops; policy/test weakening.

## Tests required
Positive: bounded prompt/output reservation, cache accounting, critical use of reserve, deterministic clean rollover, successful reconciliation.

Negative/bypass: large input-small output, malformed/stale pricing/usage/ledger, insufficient budget, routine reserve access, alternate ledger, deletion after initialization, unresolved month rollover, unsafe AI-proposed task, and reservation consistency checks. CI must run the full suite on the exact final PR head before merge.

## Rollback
Rollback provider code, this ADR, pricing version/table, ledger schema, workflow integration, orchestrator integration and tests as one tuple. Paid autonomous planning remains disabled in the rollback state. Preserve audit/usage records; never silently reset spend.

## Recovery
Treat every unresolved reservation as potentially billed. Reconcile against provider-observable usage/billing when available; otherwise keep it quarantined. Restore only from a durable valid ledger/checkpoint, then replay fixed negative/concurrency/timeout tests before re-enabling paid routing.

## Residual risks
Provider billing may expose information not available synchronously to the client. The design therefore favors false blocking over overspend: ambiguous requests retain reservations. The conservative byte-derived input bound may reserve materially more than actual cost.

## Obsolescence triggers
Re-review on pricing/model/context-window changes; cache/billing semantics changes; API usage-schema changes; ledger/concurrency backend changes; retry/fallback changes; new autonomous tool-loop capability; budget/reserve changes; secret-store changes; or any mismatch between local and provider-reported spend.
