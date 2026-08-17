# ADR-018 — Durable Mission Queue, Operations and Notifications

Status: Accepted for Phase 4 Gate 13
Parent: #510

## Decision
NEXUS Mission Control is a deterministic orchestration layer above bounded workers. It owns mission/task intent, dependency ordering, idempotency, leases, cancellation, recovery and operator notifications. It does not own live trading, production, credentials, billing, signing or irreversible financial authority.

The path is:

`Mission spec -> DAG validation -> readiness -> circuit/resource checks -> bounded lease -> worker/runner -> identity-bound result -> retry/recovery or terminal state -> Mission Control projection`

The existing Agent Manager/transport remains the lower-level worker execution mechanism. Gate 13 defines the durable mission semantics that can feed it.

## Mission and task contract
Every mission has an immutable mission ID and idempotency key, priority, authority level, deadline, bounded parallelism and task DAG. Every task has a unique task ID and idempotency key, priority, dependencies, authority, owner group, timeout, bounded attempt budget, optional local-node requirement and explicit provider/data/strategy/risk circuit requirements.

Unknown fields fail exact-schema validation. Dependency cycles, unknown dependencies, duplicate IDs and duplicate idempotency keys fail before runtime. Policy cannot autonomously authorize L4.

## Scheduling and ownership
Only dependency-complete tasks become ready. Ready tasks are ordered by priority and stable task ID. Parallel leases are capped by both mission and policy ceilings. A lease binds mission, task, owner, attempt, expiry and a deterministic attempt-scoped dispatch key.

The selected owner is explicit and deterministic from the available owner group. A result cannot mutate task state unless task ID, current lease ID and lease owner match.

## Idempotency and bounded retry
Commands/results carry command IDs. Replaying an already-processed command returns the exact current state without duplicate execution or state transition.

Direct retry is limited to explicitly transient failure classes: network unavailable, provider unavailable and local node offline. Persistent/unknown failures become blocked for root-cause handling; corrupt-state and policy-denied failures fail closed. Attempt count is bounded by both task and policy.

## Timeout, cancel and restart recovery
Each lease has a bounded timeout. Mission deadlines fail remaining work closed. Mission pause/resume, task cancel, mission cancel and notification acknowledgement are deterministic idempotent commands.

On restart, an expired lease is never assumed successful. If retry budget remains, it is returned to ready state with a recovery notification and a new attempt will receive a different dispatch key. If the budget is exhausted, it fails closed. No old lease/dispatch identity is reused.

## Offline local node and circuit breakers
Tasks may explicitly require the local node. Local-node offline state blocks those tasks without consuming a lease. Recovery re-enables them only after the environment reports the dependency restored.

Provider, data, strategy and risk circuits are explicit inputs. An open required circuit blocks the task. Stale data has a separate deterministic reason. Resource and budget limits block scheduling before a worker lease is issued.

## Notification center
Mission Control emits deduplicated bounded notifications for:

- failures and retry exhaustion;
- generic blocks and local-node offline state;
- stale data;
- provider/data/strategy/risk circuit breaks;
- budget limits;
- resource limits;
- recovery/restart events;
- owner-required L4 actions.

Notifications are independently acknowledgeable and acknowledgement is durable/idempotent.

## Durability
The complete mission state is canonical JSON bound by SHA-256. Durable writes use temporary-file + fsync + atomic replace. Corrupt or tampered state fails validation rather than silently resuming.

A compact read-only Mission Control projection exposes mission status, queue counts, agents, runners, local-node state, data state, provider state, paper state, circuit states, limits and unacknowledged notifications. Gate 14 owns the stronger dashboard/access security boundary.

## Safety boundary
Mission Control can orchestrate only the bounded authority granted by policy. L4 is owner-required. No exchange credential, private key, live order, withdrawal, production promotion/deployment, billing mutation, signing, merge authority or irreversible financial action is introduced by this gate.
