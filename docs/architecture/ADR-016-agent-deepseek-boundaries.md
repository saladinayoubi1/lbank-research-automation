# ADR-016 — Multi-Agent and DeepSeek Execution Boundaries

Status: Accepted for Phase 4 Gate 11
Parent: #510

## Decision
NEXUS uses the existing persistent Agent Manager as the sole owner of agent task lifecycle. Workers are leased bounded tasks; they do not own the mission, cannot create authority, and cannot mark their own work verified.

The runtime path is:

`dependency DAG -> capability/authority match -> lease -> transport dispatch -> worker result -> identity-bound ingestion -> independent verification or triage -> terminal state`

## Ownership and identity
Every dispatched lease binds:

- task ID;
- lease ID;
- stable task-lifecycle correlation ID;
- lease-scoped dispatch ID;
- worker ID;
- explicit transport;
- phase/gate;
- capability requirements;
- acceptance criteria;
- authority level;
- attempt number.

The correlation ID is stable across producer, retry, RCA and independent-verification leases for the same task. The dispatch ID changes whenever the lease, worker or attempt changes. Results must exactly match task, lease, correlation, dispatch, worker and transport identities. Unknown result fields fail closed.

A stale artifact from an older lease cannot complete a newer lease. A spoofed worker, route, correlation or dispatch identity is rejected.

## Real verification and recovery dispatch
Independent verification is not a local bookkeeping state. When a producer succeeds, the manager issues a new verifier lease. Transport detects the new lease identity even if an old dispatch ID remains in durable runtime state, dispatches the verifier, preserves `VERIFYING` state while the verifier runs, and accepts completion only from that verifier lease.

Root-cause-analysis leases use the same transport mechanism. Direct retry remains limited to the manager's proven transient failure classes; deterministic or unknown failures go through root-cause-first triage.

## Worker authority
The Agent Manager retains explicit worker capability sets, resource affinity, maximum authority, concurrency capacity, dependency ordering, five-minute leases/heartbeats, statuses and independent-verifier rules. L4 tasks remain owner-required and cannot be dispatched or ingested autonomously.

## DeepSeek provider boundary
DeepSeek remains a bounded advisory worker, not an execution authority. Paid routing is off unless the repository-controlled budget gate is enabled. The provider retains the existing monthly hard cap, reservation ledger, ambiguous-charge quarantine, pricing version, kernel lock and reconciliation behavior.

Gate 11 adds one narrowly classified outbound shape: a repository-owned `bounded NEXUS repository reviewer` advisory. It contains only bounded task metadata (task/correlation identity, worker role, title, required capabilities and acceptance criteria). It must not contain raw chat, credentials, private account data, live-trading instructions, production mutation, billing or signing authority. Existing pre-egress sensitive-content rejection and incidental identity redaction still run before budget reservation or network I/O.

DeepSeek evidence records provider, selected model, request cost, monthly spend/remaining budget and correlation/dispatch identity. Provider/budget errors return deterministic failure classes to Agent Manager triage rather than being treated as completion.

## Executor schema
Dispatch and result envelopes use exact schema version 2. The executor rejects unknown fields, unsupported transports and L4 payloads. It echoes task/lease/correlation/dispatch/worker/transport identity in every result.

Deterministic workers refuse to fabricate success for reasoning tasks they cannot perform.

## Security and paper/live boundary
This gate introduces no credentials disclosure, live exchange order path, withdrawal, production promotion/deployment, billing mutation, signing, merge authority or irreversible financial authority. DeepSeek and all other agents remain below the frozen owner-only L4 boundary.
