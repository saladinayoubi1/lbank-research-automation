# NEXUS Phase 5 Durable Supervisor State

Status: Gate 2 candidate / shadow only
Parent: #583
Depends on: Gate 1 / #584

## Decision

Phase 5 introduces an explicit `StateStore` boundary and a durable SQLite implementation for persistent-volume deployments. GitHub Actions cache is **not** an authoritative Phase 5 state store. The existing Phase 4 cache-backed coordinator remains previous-valid behavior until Gate 8 shadow/cutover evidence.

The first durable implementation is deliberately small and deterministic. It proves state semantics before any external database or workflow cutover. A later backend may replace SQLite behind the same contract when availability requirements justify it.

## State invariants

Each mission has an immutable snapshot stream with:

- monotonically increasing `generation`;
- canonical bounded JSON state;
- SHA-256 payload digest;
- explicit parent generation + digest;
- transition kind (`normal` or `recovery`);
- recovery quarantine generation list;
- durable creation timestamp.

Normal writes use `BEGIN IMMEDIATE` and exact compare-and-swap against the observed generation. A stale writer cannot commit after another writer advances the stream.

Identical payload writes are no-ops rather than heartbeat-generated snapshot churn.

## Corruption behavior

Corruption never means `runtime_missing` and never causes a template reset.

A normal cycle fails closed if the current tip has:

- unsupported schema/transition type;
- malformed/non-canonical/oversized payload;
- digest mismatch;
- missing/invalid parent;
- parent digest substitution;
- an invalid recursively referenced parent chain;
- malformed recovery quarantine metadata.

No new normal state may be appended to an invalid tip.

## Previous-valid recovery

Recovery is explicit and race protected.

`recover_to_previous_valid(mission_id, expected_tip_generation)`:

1. locks the database for an immediate write transaction;
2. verifies the exact expected tip is still current;
3. requires that current tip to be invalid;
4. finds the newest recursively valid older state;
5. **does not delete or rewrite** the bad rows;
6. appends a new higher generation of kind `recovery` pointing to the previous-valid generation/digest;
7. records every intervening generation as quarantined.

The recovered state is rebound through the current Gate 1 Mission contract before it is reported usable. A contract/spec revision therefore cannot resurrect incompatible completion evidence.

## Storage / deployment boundary

The SQLite file must live on a real persistent volume when activated. Storing the file solely in a GitHub Actions cache does not satisfy Gate 2. This PR does not cut over the coordinator or claim cross-node high availability.

Gate 8 will decide activation after shadow comparison, crash/restart, corruption, local-node outage and recovery evidence. If stronger availability is required, a transactional external backend can implement the same generation/CAS/immutable-history semantics without changing mission authority.

## Authority

This state layer persists bounded Supervisor metadata only. It creates no live-order, private credential, withdrawal, production, billing, signing or deterministic Risk-bypass authority. L4 remains owner-required.
