# ADR-005: NEXUS architecture baseline and authority boundaries

- Status: Proposed
- Scope: Research and paper trading only
- Issue: #94
- Version: 1.0.0

## Context

NEXUS is expanding from public-market-data research infrastructure toward crypto and FX research, strategy evaluation, deterministic risk control, paper execution, and dashboard visibility. The primary failure mode to avoid is architectural erosion: shared domain code importing adapter or UI details, strategy logic coupling directly to execution, persisted schemas changing without migration evidence, and AI output gaining implicit authority over risk or order decisions.

This ADR defines the stable module boundaries, dependency direction, authority model, compatibility rules, and recovery behavior that all later slices must preserve.

## Decision

NEXUS will use a ports-and-adapters architecture with deterministic domain and risk layers at the center. Market-specific, broker-specific, exchange-specific, UI-specific, persistence-specific, and AI-specific behavior must remain behind explicit adapters and versioned contracts.

Allowed high-level dependency direction:

```text
Crypto Adapter ─┐
Forex Adapter  ─┼──> Market Core ──> Research Lab ──> Strategy Lab
Data Adapters  ─┘                         │                 │
                                          v                 v
                                   Regime Detector ──> Decision Engine
                                                              │
                                                              v
                                                     Deterministic Risk Engine
                                                              │
                                                              v
                                                       Paper Execution
                                                              │
                                                              v
                                                   Portfolio / Event Store
                                                              │
                                                              v
                                                    Dashboard API Adapter
```

The diagram is directional, not cyclical. Dashboard, exchange, broker, storage, and LLM implementations may depend on public contracts; protected domain modules may not import those implementations.

## Module boundaries

### Market Core

Owns canonical symbols, timeframes, candles, market events, timestamps, decimal-safe numeric rules, validation primitives, and shared market semantics.

- Inputs: versioned canonical market-data contracts.
- Outputs: validated market-domain objects or explicit rejection reasons.
- Allowed dependencies: standard library and approved pure-domain utilities.
- Forbidden dependencies: exchange SDKs, broker SDKs, HTTP/UI frameworks, LLM clients, persistence implementations.
- Failure behavior: fail closed without mutating previous-valid state.

### Crypto Adapter

Translates crypto venue data and metadata into Market Core contracts.

- May contain venue-specific symbol, funding, perpetual, and session semantics.
- Must not leak credentials, private endpoints, or live-order commands into shared contracts.
- Must not add crypto conditionals to Market Core.

### Forex Adapter

Translates broker or public FX data into Market Core contracts.

- May contain session, rollover, quote convention, pip, forward, and calendar semantics.
- Must not leak broker credentials or live-order commands into shared contracts.
- Must not add FX conditionals to Market Core.

### Research Lab

Owns evidence ingestion, dataset qualification, reproducibility metadata, experiment registration, benchmark definitions, and research-result packages.

- Must reject invalid, stale, incomplete, substituted, or unqualified datasets.
- Research output is evidence, not execution authority.

### Strategy Lab

Owns versioned strategy hypotheses, features, parameters, benchmarks, transaction-cost assumptions, walk-forward and out-of-sample evaluation, sensitivity analysis, regime breakdown, drawdown, failure modes, and stop criteria.

- Promotion states: Research -> Candidate -> Shadow/Paper.
- Direct promotion to live execution is prohibited.
- Strategy packages must be reproducible and immutable once evaluated.

### Regime Detector

Produces versioned, bounded, explainable regime classifications with confidence and source trace.

- Regime output is advisory context.
- Missing, stale, conflicting, or unsupported classifications must not silently default to permissive risk.

### Decision Engine

Combines validated strategy outputs, regime context, portfolio context, and policy references into a structured decision proposal.

- Outputs proposals only.
- Must include strategy version, model version where applicable, evidence/source trace, correlation ID, causation ID, and deterministic input digest.
- Cannot bypass Risk Engine.

### Deterministic Risk Engine

Owns final authorization for every paper-trading state transition.

- Enforces exposure, concentration, leverage, drawdown, stale-signal, duplicate-signal, session, kill-switch, and policy-version rules.
- LLM or agent output cannot change policy or override rejection.
- Unknown, malformed, stale, duplicated, reordered, or unsupported input is rejected.

### Paper Execution

Simulates order, fill, fee, slippage, stop, target, reduce, reverse, close, and end-of-session behavior.

- Hard boundary: `paper_trading_only=true`.
- Live-order, withdrawal, credential, production-promotion, or billing fields are prohibited.
- All transitions require an accepted Risk Engine decision.

### Portfolio / Event Store

Persists append-only, versioned events and reconstructs state through a pure deterministic reducer.

- Canonical serialization and digest chaining are required.
- Duplicate IDs, sequence gaps, reordering, tampering, partial writes, and unknown event types fail closed.
- Failed candidate replay cannot replace previous-valid state.

### Dashboard API Adapter

Reads approved summaries and submits commands only through versioned application ports.

- It may not mutate event-store, portfolio, execution, or risk state directly.
- It must not expose sensitive source data outside an explicit allowlist.
- Network exposure and report provenance remain subject to #89 and #91.

## AI and agent authority boundary

LLMs and agents may classify, summarize, propose, prioritize, explain, and generate structured research artifacts. They may not:

- authorize final trading decisions;
- change deterministic risk policy;
- create or use financial credentials;
- place real orders or withdrawals;
- promote a strategy directly to real execution;
- suppress evidence, failure modes, or residual risk.

Every AI-assisted decision artifact must record model/version identity, prompt or policy version where appropriate, source/evidence trace, input digest, output schema version, and deterministic validation result.

## Contract and schema policy

- Public module contracts and persisted schemas require semantic versions.
- Backward-incompatible changes require an ADR, migration plan, compatibility window, rollback plan, and recovery test.
- Unknown fields are rejected in protected persisted and command contracts unless a contract explicitly defines forward-compatible extension points.
- Binary floating-point is prohibited for persisted accounting quantities and prices.
- UTC is mandatory for persisted timestamps.

## Definition of Done

A change is complete only when applicable evidence exists for:

1. fixed-head green tests;
2. regression coverage for bug fixes;
3. contract and documentation updates;
4. observability and deterministic error evidence;
5. rollback and clean recovery;
6. residual-risk statement;
7. zero unresolved review threads;
8. explicit confirmation that no live trading, credential, billing, or production path was introduced.

## Threat boundaries and abuse cases

Primary trust boundaries:

- external market source -> adapter;
- adapter -> Market Core;
- research evidence -> Strategy Lab;
- strategy/AI output -> Decision Engine;
- Decision Engine -> Risk Engine;
- Risk Engine -> Paper Execution;
- event candidate -> previous-valid event state;
- stored summaries -> Dashboard API -> browser.

Required abuse cases include malformed, stale, duplicate, reordered, oversized, substituted, tampered, partially written, unsupported, and adversarial inputs; direct UI mutation; adapter leakage; AI-policy override; schema downgrade; circular dependency; silent exception; and disabled validation gate.

## Alternatives rejected

- Monolithic service: rejected because it couples research, strategy, risk, execution, persistence, and UI changes.
- Venue-first architecture: rejected because crypto and FX details would leak into shared logic.
- Agent-authorized execution: rejected because probabilistic output is not an acceptable final risk gate.
- Mutable snapshot-only accounting: rejected because deterministic replay, attribution, recovery, and tamper evidence would be weaker.

## Rollback and recovery

This ADR is additive and introduces no runtime behavior. Rollback is deletion of this document and its contract registry before dependent code merges.

For later implementation slices, recovery must preserve the previous-valid research dashboard and data pipeline, quarantine invalid candidate state, restore from versioned evidence, rerun fixed-head tests, and verify that no credential or live-execution path exists.

## Residual risks

Documentation cannot enforce dependency direction or runtime authority. An executable validator, tests, and CI integration are required in later slices. External signing identity, trust root, protected production approval, credential custody, independent disaster recovery, and isolated reproducible-build infrastructure remain outside this ADR and must stay blocked.

## Obsolescence triggers

Revisit this ADR after a persisted schema change, new market class, new execution model, authentication or remote dashboard exposure, storage-engine change, risk-policy authority change, AI model authority change, production-deployment proposal, false-green incident, recovery failure, or material dependency inversion.
