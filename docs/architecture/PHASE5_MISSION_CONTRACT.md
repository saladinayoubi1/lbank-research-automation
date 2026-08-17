# NEXUS Phase 5 Mission Contract

Status: Phase 5 Gate 1 shadow contract
Parent: #583

## Purpose

Phase 5 separates Supervisor identity from project phase numbering. A phase is planning metadata; it must not silently reset, authorize, or invalidate an otherwise identical bounded mission task.

The first Phase 5 slice is intentionally additive. It does not replace the Phase 4 Fast Agent Coordinator or widen authority. The new mission runner remains a shadow path until later Phase 5 gates prove durable state, fencing, typed evidence, chaos recovery and cutover safety.

## Canonical mission identity

A mission definition uses `nexus.phase5-mission.v1` and binds:

- `mission_id`;
- `mission_revision`;
- versioned policy;
- workers/capabilities;
- a deterministic acyclic task graph.

Each task receives a SHA-256 `spec_digest` over authorization/acceptance semantics:

- mission schema / mission id / mission revision / policy version;
- task id;
- dependencies;
- required capabilities;
- authority level;
- acceptance criteria.

The digest deliberately excludes display/scheduling metadata such as phase, gate, title, priority and preferred resource. Changing those fields cannot strengthen authority or inherit a different acceptance contract.

Changing authority, dependencies, required capabilities, acceptance, mission revision or policy version produces a new `spec_digest` and prevents prior runtime completion/evidence from being inherited.

## Dependency safety

The contract rejects:

- duplicate worker or task ids;
- unknown dependencies;
- duplicate dependencies;
- self dependencies;
- dependency cycles;
- invalid authority values;
- malformed capabilities/acceptance criteria.

No partially valid DAG is executed.

## Runtime continuity

Compatible runtime state is inherited only when both task id and `spec_digest` match. A compatible P4/P5 or later phase metadata transition therefore preserves work; a security/acceptance semantic change does not.

Tasks removed from the current mission definition are retained as `QUARANTINED` historical runtime records rather than silently disappearing.

## Corrupt-state boundary

The Phase 5 shadow runner distinguishes a missing runtime from a corrupt/unsupported runtime:

- missing runtime: a new mission may start;
- corrupt JSON, wrong root type, unsupported runtime schema, or wrong mission identity: fail closed.

It never treats corrupt state as an empty state/template reset.

Gate 2 will replace the current file-backed shadow runtime with an authoritative durable StateStore and previous-valid recovery protocol. GitHub Actions cache is not accepted as the final authoritative Phase 5 state store.

## Authority

This contract is research/backtest/paper-only. L4 remains owner-required. It creates no live-money, exchange credential, withdrawal, production promotion, billing or signing authority.

## Migration rule

1. Validate this contract and shadow runner under existing repository CI.
2. Add durable StateStore and fencing behind the new mission contract.
3. Compare shadow decisions with the current coordinator on fixed inputs.
4. Exercise restart/corruption/stale-attempt/provider/local-node chaos.
5. Cut over only after Phase 5 Gate 8 evidence; otherwise keep the current Phase 4 control plane as previous-valid behavior.
