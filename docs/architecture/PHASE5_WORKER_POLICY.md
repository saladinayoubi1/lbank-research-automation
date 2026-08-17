# NEXUS Phase 5 Worker / Provider Policy Plane

Status: Gate 5 candidate / shadow contract
Parent: #583
Depends on: Gates 1-4

## Decision

Static worker authority, capabilities, trust domain and concurrency limits come only from the versioned Mission registry. Dynamic runtime health may report availability, active load and bounded dispatch-cost estimates, but it may not add or change capabilities, authority, trust domains or enabled state.

Dynamic schema: `nexus.phase5-worker-runtime.v1`.
Routing result: `nexus.phase5-routing-decision.v1`.

## Routing order

A worker is eligible only when all hard constraints pass:

- statically enabled;
- authority max covers the task;
- required capabilities are present in the static registry;
- runtime health exists and is not `offline`;
- declared static concurrency capacity is not exhausted;
- external paid provider has explicit already-approved budget authorization;
- estimated dispatch cost is within the caller's bound.

Eligible workers are ranked deterministically by:

1. online before degraded;
2. preferred-resource matches;
3. lower bounded estimated cost;
4. lower utilization;
5. stable worker id tie-break.

Missing runtime health is unknown/fail-closed, not implicitly online. An offline Windows node is excluded and safe cloud alternatives remain eligible. A provider outage or paid-budget denial must not block unrelated work when another worker satisfies the task.

## DeepSeek

`deepseek-external` remains optional/advisory. Runtime `paid_budget_authorized=true` is not itself billing authority: it represents the output of the separately approved bounded budget control. Without that positive input, paid routing is denied. Gate 5 does not close or weaken #232 and does not require DeepSeek for Phase 5 progress.

## Anti-self-promotion

Runtime snapshots accept only health/load/cost/budget observation fields. Fields such as `authority_max`, capabilities, resources, trust domain, enabled state or verifier status are rejected rather than merged. A compromised worker therefore cannot self-advertise stronger authority through health telemetry.

## Cutover boundary

This module remains the Phase 5 shadow routing policy. Gate 8 must integrate actual health observations from GitHub/Windows/provider transports, bind them to authenticated runtime identities, compare routing with the previous-valid coordinator, and exercise outage/reconnect/partial-state chaos before canonical cutover.

## Authority

Research/backtest/paper-only. L4 is never routed autonomously. No live-money, private credentials, withdrawal, production, billing, signing or deterministic Risk-bypass authority is added.