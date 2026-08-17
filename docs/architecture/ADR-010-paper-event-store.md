# ADR-010: Deterministic append-only paper event store

- Status: Accepted
- Date: 2026-08-17
- Phase: 4, Gate 5
- Scope: Paper trading only

## Context

NEXUS needs a reproducible record of simulated decisions and accounting effects. Dashboard projections, recovery, audits, and later paper-execution work must all derive from one deterministic history. A mutable state table alone cannot prove order, detect tampering, preserve manual-versus-automatic provenance, or reconstruct the last valid portfolio after a failure.

The trust boundary is strict: research data and strategy outputs are untrusted inputs; deterministic risk policy may allow or reject paper intents; this store records paper-domain facts only. It has no exchange credentials, signing authority, withdrawal path, billing path, or live-order authority.

## Decision

Use a versioned, append-only event envelope implemented by `paper_event_store.py`.

Every event includes:

- schema version, unique event ID, aggregate ID, exact sequence, UTC occurrence time;
- correlation and causation IDs;
- explicit automatic/manual provenance, source and receipt timestamps, timeframe, confidence, strategy version, and policy version;
- previous-event, payload, and complete-event SHA-256 digests;
- a mandatory `paper_trading_only: true` authority marker;
- an exact event-type payload schema using decimal strings rather than binary floating point.

Replay is the sole supported reconstruction path. It verifies exact schemas, canonical serialization, digest integrity, aggregate identity, event IDs, sequence continuity, causal timestamp order, bounded signal freshness, and state invariants before producing a new immutable `PortfolioState`.

The event vocabulary covers demo accounts, signals, paper order intents, risk decisions and rejections, simulated fills, position lifecycle, stops, targets, fees, slippage, equity snapshots, kill-switch transitions, and session boundaries.

## Deny-by-default rules

The store rejects:

- unknown event types, envelope fields, payload fields, or provenance fields;
- non-paper authority;
- floats, non-finite decimals, non-positive quantities/prices/opening cash;
- stale or causally reversed provenance;
- duplicate IDs, missing/duplicate/reordered sequences, chain breaks, and tampered content;
- invalid position transitions and accounting charges;
- fields suggesting credentials, keys, exchange orders, withdrawals, production, billing, or signing.

No adapter in this decision may submit orders, hold secrets, or convert paper events into live exchange actions.

## Recovery and rollback

Replay is transactional from the caller's perspective. `replay_or_previous` applies a candidate batch to an immutable copy; if any event fails validation or reduction, it returns the previous valid snapshot with zero applied candidate events. The invalid batch remains rejected and requires operator investigation or a corrected event stream. History is never rewritten to hide an invalid event.

Rollback means selecting an earlier verified digest/sequence snapshot and replaying forward from its next event, never deleting or mutating accepted history.

## Abuse cases considered

- Payload or envelope tampering after acceptance.
- Duplicate delivery and out-of-order retries.
- Sequence gaps caused by partial writes.
- Stale strategy signals presented as current decisions.
- Manual intervention presented as automatic provenance.
- Float, NaN, or infinity accounting contamination.
- Attempts to inject credential or live-trading fields.
- Cross-account event mixing.
- Closing or reducing nonexistent positions.
- Oversized replay used for resource exhaustion.

## Consequences

Benefits:

- deterministic state reconstruction and reproducible accounting;
- explicit audit trail across automatic and manual decisions;
- fail-closed recovery with stable last-known-good state;
- a safe contract for later paper execution and dashboard projections.

Costs:

- schema evolution requires a new explicit version and migration/replay tests;
- append-only history requires retention and snapshot planning;
- cryptographic chaining detects tampering but is not a digital signature.

## Residual risks and follow-up

- Persistent storage, atomic append semantics, snapshot retention, and backup verification remain deployment concerns.
- Global duplicate detection across compacted snapshots requires a persisted event-ID index or equivalent deduplication key.
- Cryptographic authenticity would require a separately governed signing design; it is intentionally out of scope.
- Gate 6 must consume this contract without adding live-trading authority.

## Obsolescence criteria

Replace this ADR only if NEXUS adopts a versioned event contract that preserves deterministic replay, exact provenance, append-only integrity, paper-only authority, fail-closed recovery, and equivalent regression evidence.
