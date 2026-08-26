# NEXUS Regime Strategy Runtime v1

## Contract

The runtime connects a verified three-timeframe context and the regime strategy
selector to the existing automated signal, Deterministic Risk, and Paper
execution path.

```text
15m + 1h + 4h context
  -> regime strategy selection
  -> weighted family proposal
  -> automated signal pipeline
  -> Deterministic Risk
  -> isolated Paper portfolio
  -> independent verifier
  -> append-only runtime evidence
```

## Safety invariants

- Input lanes must exactly match the selected strategy families.
- Every lane must use a different initialized Paper portfolio.
- Strategy identity and version must match the selector evidence.
- Allocation scales proposal quantity; it never creates an order directly.
- Every resulting signal passes the existing Deterministic Risk implementation.
- A Risk denial is recorded and cannot reach Paper execution.
- A preserve-cash selection requires zero execution lanes.
- Live authority and automatic strategy promotion remain false.
- Evidence is persisted only after independent verification and uses a
  create-once filename bound to the runtime digest.
- Persistence stages and synchronizes a temporary file before an atomic
  create-once link; restart reload rechecks content, verifier, and filename.
- The verifier recomputes Deterministic Risk from the recorded signal, state,
  and policy; a producer cannot rewrite Risk and merely recompute the outer digest.
- Full Paper events are schema-validated and their digest chain, portfolio binding,
  and allow/reject semantics are checked before persistence or restart recovery.
- The verifier re-runs both strategy selection and the complete deterministic Paper
  pipeline from recorded inputs, rejecting even fully rehashed allocation, fill,
  accounting, or terminal-state substitutions.

## Verification

`tests/test_nexus_regime_strategy_runtime.py` covers successful weighted Paper
execution, preserve-cash behavior, lane mismatch, strategy substitution, Risk
denial, determinism, and input immutability.
It also covers rehashed Risk forgery, malformed evidence, append-only persistence,
selector and pipeline replay, filename substitution, tampering, and restart verification.
