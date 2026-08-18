# NEXUS 4.0 Product Integration Contract

## Purpose
NEXUS 4.0 is the user-facing integration layer for backend capabilities already implemented in the repository. A market viewer alone is not an acceptable NEXUS product delivery.

## Required product surfaces
- Mission Control: mission, queue, agents, runners, providers, notifications and local-node/data state when an authoritative runtime projection exists.
- Paper/Demo Trading: durable demo account, positions, deterministic Risk, simulated fills, fees/slippage, stops/targets, PnL/equity and an append-only replayable journal.
- AI Room: repository Project Memory context plus the existing authority-gated control plane. It may observe/propose or run only policy-approved bounded routes.
- Strategy Lab: real Strategy Factory families and qualification path.
- Research Lab: evidence-oriented research integration; unavailable runtime evidence must be displayed as unavailable rather than fabricated.
- Decision/Risk: deterministic Paper Risk policy and reason codes.
- Audit/Replay: tamper-evident paper event chain and future observability projection when present.
- Live/Main: visible as a product area but locked and owner-controlled under the current authority contract.

## Canonical architecture
The product browser UI talks only to the local NEXUS product gateway. The Windows Electron shell launches the packaged Python product sidecar and does not reimplement Risk, Paper Execution, AI authority, Project Memory or Strategy qualification in JavaScript.

```text
Electron shell
    -> loopback-only NEXUS Product Gateway
        -> Project Runtime
            -> deterministic_risk.py
            -> paper_execution.py
            -> paper_event_store.py
        -> AI Room / AI Control Plane
        -> Mission Control read model
        -> Strategy Factory / Research integrations
```

## Authority invariants
- Research / Backtest / Paper only.
- Deterministic Risk remains final Paper execution authority.
- No private exchange credential surface is added.
- No live order, withdrawal, signing, billing or production-promotion authority is added.
- Live/Main remains `LOCKED / OWNER-CONTROLLED` until a future explicit higher-risk contract is approved.
- Missing or corrupt runtime state fails closed and must not be replaced with fabricated UI state.

## Delivery gate
A Windows build is acceptable only when CI:
1. runs product runtime/API tests;
2. packages the canonical Python gateway as an isolated sidecar;
3. smoke-tests the sidecar over loopback;
4. verifies Paper is active and Live authority is false;
5. verifies the product UI contains Paper, AI Room and Live/locked surfaces;
6. packages both Setup and Portable artifacts.
