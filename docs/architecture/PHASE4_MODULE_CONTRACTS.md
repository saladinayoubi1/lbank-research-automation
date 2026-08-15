# NEXUS Phase 4 Module Contracts

Status: Gate 1 baseline
Parent: #510
Contract version: `phase4-modules/v1`

## Global dependency rule
Dependencies flow toward deterministic domain authority, never away from it. Shared/core modules must not import dashboard/UI, provider-specific AI, exchange-specific implementation or credential-bearing code. Adapters translate external semantics into canonical contracts; they do not redefine core authority.

## Market Core
Owns canonical market-data objects, symbol/market/timeframe identity, candle finality, readiness/integrity/provenance contracts.
Allowed inputs: validated adapter output.
Allowed consumers: Research Lab, Strategy Lab, Regime Detector.
Forbidden: UI mutation, AI-provider dependency, execution authority, credential fields.
Failure: quarantine/explicit unavailable state.

## Crypto / FX Adapters
Own source-specific public market semantics and translation into Market Core contracts.
Forbidden: silent cross-source substitution, downstream eligibility decisions, portfolio mutation.
Failure: explicit source-unavailable/semantic-mismatch reason.

## Research Lab
Owns experiments, backtests, robustness, walk-forward, out-of-sample/regime/failure analysis and reproducible experiment evidence.
Consumes only eligible Market Core datasets.
Produces qualification artifacts; cannot directly execute paper trades.

## Strategy Lab
Owns versioned strategy definitions and deterministic signal proposals.
Signals bind strategy version, dataset revision, timeframe, timestamps, confidence/provenance, correlation/causation IDs.
Forbidden: direct paper execution or risk bypass.

## Regime Detector
Owns deterministic/validated regime classification used as decision context.
Forbidden: execution authority and direct state mutation.

## Decision Engine
Combines qualified strategy proposals and approved context into structured paper action proposals.
Every output is non-authoritative until deterministic Risk validation.

## Deterministic Risk Engine
Final authority for paper execution eligibility.
Owns position/exposure/loss/session/stop-target/staleness/duplicate/eligibility/kill-switch/circuit-breaker policy.
No AI, UI, strategy, provider or adapter may bypass it.

## Paper Execution
Owns deterministic demo-only execution simulation: open/close/reduce/reverse, bounded fills, fees/slippage, stops/targets.
Consumes Risk-approved commands only.
Forbidden: private exchange API, real orders, credentials, withdrawal or live mode.

## Portfolio / Event Store
Owns append-only versioned events and pure deterministic replay/reducer contracts for cash, equity, positions, PnL inputs, stops/targets and bot state.
Persisted accounting uses decimal-safe representation and UTC deterministic ordering.
Corrupt/ambiguous candidate state cannot replace previous-valid state.

## Config / Registry Layer
Owns immutable/versioned identities and active-version pointers for datasets, strategies, experiments, risk policies, AI providers/models, agent capabilities, feature flags and API/schema compatibility.
No unversioned mutable config may increase authority.

## AI Control Plane
Owns chat/session identity, context provenance/freshness, intent classification, agent/tool routing, authority checks, bounded retry/timeout/cancel/delegation and structured proposals.
Authority levels: L0 Observe, L1 Propose, L2 bounded reversible execution, L3 explicitly-authorized autonomous bounded workflows, L4 owner-required.
AI cannot self-promote and cannot replace deterministic validation/risk authority.

## Agent / Provider Layer
Owns bounded specialist work. Capabilities, provider/model identity, resource/budget limits, correlation IDs, dependencies, retries/timeouts and audit evidence are explicit.
DeepSeek/auxiliary models remain advisory/bounded and have no secret, merge, production, billing, signing, live-trading or risk-policy authority.

## Project Memory
Owns durable project state/decision continuity separate from chat history.
Working context, durable state and archive/handoff are distinct.
Stale/conflicting/unverifiable memory fails closed; unnecessary raw private transcripts and credentials are forbidden.

## Mission Queue / Operations
Owns durable task priority, dependencies, idempotency, lease/ownership, bounded retries, timeout/cancel, restart recovery, local-node offline state and circuit breakers.
Does not grant domain authority merely because a task is queued.

## Dashboard / API
Owns presentation and user command adapters only.
Read and write surfaces use versioned API contracts.
No direct mutation of portfolio/event/config authority; commands enter the same validation/policy/risk path as automation.
Security boundary includes loopback/default exposure, Host/DNS-rebinding defenses, bounded parsing and explicit degraded/stale/blocked/recovery states.

## Observability / Audit
Owns appendable decision/action evidence: actor/model/agent, inputs/provenance, policy/version, decision/reason, action/tool, result/evidence and resulting state.
Observability cannot authorize behavior; missing critical evidence fails closed where the owning Gate requires it.

## Forbidden dependency examples
- Core -> Dashboard/UI
- Core -> exchange-specific adapter implementation
- Risk -> LLM/provider implementation
- Event Store -> Dashboard
- Dashboard -> Event Store mutation
- Strategy -> Paper Execution
- AI Chat -> Paper Execution bypass
- Provider -> Risk policy mutation
- Config change -> stronger authority without versioned policy/validation

## Schema/change rule
Any persisted/public contract change requires a version bump or explicit backward-compatible declaration, migration/compatibility note, rollback tuple, recovery path and regression coverage.

## Recovery rule
For each stateful module, candidate recovery must validate against the current contract/policy before replacing previous-valid state. Ambiguity preserves previous-valid state and emits deterministic reason/evidence.
