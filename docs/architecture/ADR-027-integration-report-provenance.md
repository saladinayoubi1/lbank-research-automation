# ADR-027: Bounded provenance-verified integration reports

## Status

Accepted — 2026-08-22.

## Decision

Dashboard integration files are untrusted input across this boundary:

`reviewed producer -> data/integrations -> bounded adapter -> read-only API -> local browser`.

The adapter accepts only `nexus.integration-report-envelope.v1`. The envelope binds an exact canonical report SHA-256 to an allowlisted producer, exact 40-character source commit, workflow-run identity, UTC generation time, schema and policy version. Reports older than 24 hours, more than 5 minutes in the future, unbound, digest-modified, unknown-field, oversized, linked, replaced during reading or structurally inconsistent are unavailable.

Zotero content is classified private research metadata. Research claims and evidence are internal research metadata. The API allowlist exposes counts, approved domain labels, review date and status only. Titles, creators, DOI values, notes, tags, paths, prompts and raw evidence are never emitted.

Research claims require unique identifiers and non-empty, unique references to existing evidence identifiers. Missing, duplicate, dangling or substituted references fail closed. Review dates are mandatory and cannot be more than 366 days ahead. The generated-at time, not filesystem time, controls 24-hour freshness.

## Threat model and abuse cases

Threat actors are a compromised producer, untrusted local process/user, malicious browser origin, stale-report supplier and schema-confusion attacker. Covered abuse cases include forged clean state, negative/extreme/bool counts, count mismatch, future/stale timestamps, duplicate keys, oversized JSON, symlink/hardlink/substitution, cross-report swap, producer/policy/commit/run/digest mismatch, dangling evidence and privacy-field expansion.

ADR-019 separately enforces the loopback Host/Origin gateway. Integration routes inherit that boundary and are unavailable when either gateway or report validation fails.

## Operations

Rollback: revert the Issue #91 remediation or remove `data/integrations`; routes return 503 and never fall back to network data.

Recovery: restore a reviewed producer, regenerate envelopes from the intended source commit/run, verify SHA-256 and freshness, run fixed-head positive/negative/bypass tests, and restart the loopback service.

Residual risk: the local envelope is integrity binding, not external signature or transparency-log attestation. A process that can modify both trusted code and reports remains outside this local-only boundary. Remote/production use requires a separately reviewed authenticated attestation and deployment policy.

Re-review after producer/schema/allowlist/privacy/freshness/parser/trust-root/gateway changes, report growth, remote deployment, or any false-clean, privacy, stale-data or availability incident.
