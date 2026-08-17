# ADR-017 — Project Memory, Working Context and Chat Migration

Status: Accepted for Phase 4 Gate 12
Parent: #510

## Decision
NEXUS continuity is split into three authority layers:

1. **Short-lived working context** — conversation-scoped, bounded and explicitly non-authoritative.
2. **Durable Project Memory** — repository-owned canonical state and decisions; remains the source of truth.
3. **Archive / handoff history** — immutable structured checkpoints that carry continuity evidence between chat sessions without carrying raw transcript or authorization material.

Chat state never becomes repository authority.

## Working-context contract
A working context binds:

- context and conversation identity;
- generation and expiry timestamps;
- exact repository main SHA;
- exact SHA-256 digest of the durable Project Memory state;
- phase and current gate;
- bounded summary and decision list;
- exact evidence references;
- open blockers;
- deterministic context-health measurements.

Unknown fields fail exact-schema validation. Raw transcript fields, credential/authorization fields and secret-like values are rejected. Expired or over-age working context fails closed.

## Durable-state freshness
Checkpoint creation independently validates the supplied durable Project Memory object. The repository must remain the durable source, chat must remain non-authoritative and secrets must remain forbidden. The Project Memory `current_evidence.observed_main_sha` must equal the externally supplied expected repository SHA. A stale Project Memory state cannot be checkpointed or migrated.

The working context also carries the SHA-256 digest of the exact Project Memory object. Any change to durable state invalidates the context binding until a new context is constructed.

## Context-health trigger
The health record contains used capacity, total capacity, unresolved-conflict count and stale-reference count. Health evaluation is deterministic:

- unresolved conflicts -> blocked;
- stale evidence references -> blocked;
- utilization at or above the configured threshold -> `handoff_required`;
- otherwise -> healthy.

A handoff checkpoint can be created only when the deterministic threshold is reached. Blocked or below-threshold context does not produce a migration checkpoint.

## Handoff checkpoint
A checkpoint stores only the minimum structured continuity set:

- exact repo SHA and Project Memory digest;
- phase/gate;
- bounded summary;
- decisions;
- evidence references;
- blockers;
- source context/conversation identity;
- health trigger reason;
- explicit safety flags.

The checkpoint ID and record digest are deterministic SHA-256 bindings over canonical content. Tampering, extra fields or unsafe safety flags fail validation. Raw private transcript and credentials are explicitly absent.

## Chat migration
Migration is a continuity transfer, not an authority transfer. A migration request must bind the exact checkpoint ID/digest, repo SHA, Project Memory digest and ordered evidence-reference list. Any mismatch fails closed.

The target conversation must be different from the source. Requested authority is capped by policy and cannot exceed L3. No migration can grant owner-only L4 authority.

The generated migration bundle preserves the checkpoint summary, decisions, blockers and exact evidence references. It contains explicit flags proving source repository state and evidence references were preserved and that raw transcript/credentials were not included.

## Recovery and privacy boundary
If Project Memory is stale, conflicting, secret-bearing or not repository-authoritative, continuity stops until the durable state is corrected. If working context carries stale evidence or unresolved conflicts, handoff stops rather than silently selecting one version.

No exchange credential, private key, raw private chat transcript, live-order instruction, withdrawal, production promotion/deployment, billing mutation, signing authority or irreversible financial authority is persisted or transported by this gate.
