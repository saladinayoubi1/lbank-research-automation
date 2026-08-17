# ADR-013: Deterministic paper execution and accounting

- Status: Accepted
- Date: 2026-08-17
- Phase: 4, Gate 8

## Decision

Paper operations use `paper_execution.execute_paper_command` after an allowed Gate 7 `RiskDecision`. The command, risk causation ID, and approved notional must match exactly. Execution supports bounded open, close, reduce, and same-size reverse operations.

Fill price is derived deterministically from the reference price and bounded slippage basis points. Fees, slippage cost, realized PnL, cash, and equity use `Decimal` with round-half-even quantization. Every transition produces a causally linked append-only Gate 5 event sequence and immediately replays it to prove reconstructability.

Manual and automatic signals share the same command, risk, fill, accounting, and event path. Protective stops and targets are mandatory for open and reverse operations.

## Safety boundary

This is simulation only. It has no exchange adapter, credential, private endpoint, live order ID, withdrawal, signing, billing, or production authority. Exact schemas reject unknown live-oriented fields. Session and kill-switch state fail closed.

## Recovery

A returned result is valid only after its complete candidate event sequence replays from the previous verified `PortfolioState`. Invalid commands or transitions emit no accepted result. Restart recovery uses the append-only event stream and must reconstruct the identical portfolio state.

## Obsolescence criteria

Replace only with an implementation that preserves deterministic fills and accounting, exact risk binding, event-sourced reconstruction, operation invariants, manual/automatic parity, bounded simulation, and the paper/live air gap.
