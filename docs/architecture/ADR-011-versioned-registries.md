# ADR-011: Versioned configuration registries

- Status: Accepted
- Date: 2026-08-17
- Phase: 4, Gate 6

## Context

Strategies, datasets, risk policies, AI providers, agent capabilities, feature flags, API compatibility, and experiments influence NEXUS behavior. Mutable unversioned files make replay ambiguous and can silently strengthen authority. Configuration must therefore be selected by exact version and bound to durable evidence.

## Decision

Use the contract in `versioned_registries.py` for all eight frozen registry types.

Each registry has an exact schema version, semantic registry version, lifecycle status, previous-registry digest, canonical ordered entries, and SHA-256 digest. Each entry has an ID, semantic version, enabled state, bounded authority, and exact configuration object.

Consumers must select an exact entry ID and version. There is no implicit latest-version fallback. A selected contract returns the registry digest so decisions and events can retain configuration provenance.

Transitions require:

- a strictly increasing registry version;
- a valid previous-digest chain;
- no entry downgrade;
- a new entry version for any config, authority, or enabled-state mutation;
- no self-promotion to stronger authority through configuration.

## Authority boundary

The maximum representable authority is bounded reversible execution. Registries cannot carry credentials, live-order routes, withdrawals, production promotion, billing, or signing fields. Stronger authority requires a separate owner-governed mechanism and is outside Phase 4.

AI, UI, strategies, and agents may reference a registry contract but cannot bypass deterministic risk or paper-execution validation.

## Failure and recovery

Unknown fields/types, unsupported versions, tampering, missing registry categories, duplicates, disabled entries, suspended registries, version gaps, downgrade, chain mismatch, and forbidden fields fail closed.

Rollback selects a previously verified registry digest and exact entry versions. Accepted registry history is not mutated. A failed candidate leaves the previous active registry authoritative.

## Consequences

Every behavioral input becomes reproducible and auditable. Consumers must explicitly migrate when versions change, which adds work but prevents silent behavior drift.

## Obsolescence criteria

Replace this ADR only with a contract that preserves exact-version selection, canonical integrity, monotonic migration, digest-linked history, bounded authority, and fail-closed recovery for all eight registry categories.
