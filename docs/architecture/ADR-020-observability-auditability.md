# ADR-020 — Phase 4 Observability and Auditability

Status: Gate 15 candidate
Parent: #510
Contract: `nexus.observability.read.v1`

## Decision

NEXUS records meaningful decisions/actions in a deterministic, append-only, tamper-evident audit journal. Observability is evidence only: it may expose facts and fail a Gate when required evidence is absent, but it cannot authorize strategy, risk, paper execution, provider, mission, or live behavior.

Each decision/action preserves the frozen Gate 15 chain:

`actor/model/agent -> inputs + provenance -> policy/version -> decision -> tool/action -> result -> evidence -> resulting state`

Every audit record also carries UTC time, correlation/causation identity, category/stage identity, previous-event digest, payload digest and event digest.

## Required coverage

The Gate 15 coverage validator requires evidence across the critical paper path:

`market_data -> strategy_regime -> signal -> decision -> risk -> dispatch -> paper_execution`

It also requires at least one evidence category for each minimum operational surface named by #510:

- queue status/latency/retries;
- agent/provider status or failure;
- AI usage/cost/resource budget;
- data readiness;
- strategy qualification/promotion;
- signal acceptance/rejection;
- risk decisions/denials;
- paper execution/positions/PnL/drawdown/exposure;
- recovery/replay;
- memory/context incidents;
- circuit/policy denial.

Missing critical coverage fails closed through `MissingCriticalAuditEvidence`.

## Integrity and persistence

`AuditJournal` validates exact schema, rejects duplicate event IDs, verifies the digest chain, rejects reordering/tampering, and supports bounded JSONL replay. Loading malformed, reordered or digest-invalid evidence fails without replacing a previously validated in-memory journal.

Persisted numeric metrics reject binary floating point and non-finite values. Timestamps are UTC-only.

## Operator surface

`operator_snapshot()` produces a bounded, read-only summary with category counts, incident count, coverage gaps, recent deterministic reason codes and the audit head digest. The returned contract explicitly marks `read_only: true`; it contains no command or execution authority.

## Authority effect

None. Observability cannot:

- approve or alter Risk decisions;
- execute or mutate paper positions;
- change mission/provider/strategy policy;
- disclose credentials or private exchange capability;
- create a live-order path.

## Persisted-schema effect

New append-only audit schema version `1`. The public read model is `nexus.observability.read.v1`. Future incompatible changes require a schema/contract version bump and migration/replay tests.

## Tests

`tests/test_observability_audit.py` covers:

- full Gate 15 category and decision-path coverage;
- fail-closed missing critical stage/category;
- tamper and reorder detection;
- incident/operator visibility;
- exact JSONL replay;
- UTC and decimal-safe metric validation;
- malformed persisted evidence rejection.

## Rollback and recovery

Rollback removes the Gate 15 module/contract without touching deterministic trading state. Audit recovery replays only a validated hash chain; ambiguous/corrupt candidate evidence is rejected. Observability never becomes a source of portfolio truth, so audit failure cannot silently rewrite paper accounting.

## Residual risk / next gates

Gate 16 remains responsible for concurrent writers, idempotent retry and failure taxonomy. Gate 17 remains responsible for crash/chaos recovery. Gate 19 remains responsible for measured retention, latency and resource bounds. Gate 20 must bind this audit evidence to the final fixed SHA and full E2E flow.
