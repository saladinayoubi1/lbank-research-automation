# ADR-014 — Deterministic Automated Signal Pipeline

Status: Accepted for Phase 4 Gate 9
Parent: #510

## Decision
The automated paper path is a single fail-closed chain:

`Ready Dataset -> Qualified Strategy -> Regime -> Decision -> Deterministic Risk -> Paper Execution`

The pipeline does not create a second execution authority. It validates upstream bindings, records the signal, submits the reduced execution proposal to the existing deterministic Risk authority, and invokes Paper Execution only when Risk returns `allowed=True`.

## Mandatory bindings
Each automated signal binds the market source, dataset identity and revision, dataset provenance digest, source/received timestamps, symbol/timeframe, strategy identity/version, qualification artifact identity/digest, regime identity/version/label/confidence, decision identity, decision confidence, risk-policy version, correlation ID and causation ID. The signal ID is deterministically derived from canonicalized bindings.

Unknown fields fail exact-schema validation. Dataset readiness must be `ready`; strategy qualification must be `paper_eligible` or `paper_active`; dataset/strategy/regime/decision identities must match exactly; policy version must match the Risk policy supplied for evaluation. Gate 9 intentionally accepts only paper `open` proposals until operation-aware exposure semantics are owned by Risk.

## Authority and event flow
The signal is append-only recorded before Risk evaluation. A denied Risk decision records `risk_rejection_recorded` and produces no fill or position mutation. An allowed decision enters the existing `execute_paper_command` path, which independently verifies the Risk decision signal ID and approved notional before simulating a fill.

Manual and automated execution still share the same Risk/Paper Execution authority. This ADR only defines the automated producer path.

## Paper/live air gap
No exchange adapter, private API, credential, live-order, withdrawal, production, billing, signing or irreversible authority is introduced. The bound signal and emitted events are explicitly paper-only. Exact schemas reject injected live-oriented fields.

## Recovery and determinism
Inputs are immutable to the pipeline. Identical validated inputs and prior PortfolioState produce an identical signal ID, Risk decision, event chain and resulting state. Event-store digest chaining and replay remain the recovery authority; corrupt or ambiguous state is rejected by the existing event-store contract.

## Failure semantics
Readiness, qualification, provenance, identity, timestamp, confidence, policy or schema mismatch fails before Risk/Paper Execution. Risk denial is a valid deterministic terminal result and is audit-visible. Execution cannot occur without the exact Risk-approved signal/notional binding.
