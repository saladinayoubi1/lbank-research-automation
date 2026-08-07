# NEXUS Durable Decision Log

This is an append-oriented log. Do not rewrite history to make later decisions look inevitable. Mark superseded decisions explicitly.

## 2026-08-07 — Durable memory is part of the architecture
Status: ACTIVE

Decision: Project continuity must not depend on any single ChatGPT conversation, browser session, laptop process, or optional model provider. Important goals, constraints, architecture decisions, current state, failure lessons and recovery procedures belong in repository-owned durable memory.

Reason: Long-running chat context can become unavailable or incomplete. Losing a chat must not reset project direction.

## 2026-08-07 — Incremental autonomy, not unrestricted autonomy
Status: ACTIVE

Decision: NEXUS receives authority in bounded layers. Low-risk retries, health checks and reversible recovery can be automated. Changes to core goals, security boundaries, destructive operations, credentials, production/release authority and other high-impact decisions require explicit human authorization unless a later reviewed policy narrowly delegates them.

## 2026-08-07 — Memory stores decisions, not secrets or full private transcripts
Status: ACTIVE

Decision: Persist concise operational facts, decisions and lessons. Do not persist API keys, passwords, tokens, private financial credentials, or unnecessary verbatim chat history.

## Historical anchors imported from project handoff
Status: ACTIVE unless superseded by newer repository evidence

- Research-only scope; no real trading or financial-account control.
- LBank and Bybit data namespaces must not be silently mixed.
- Invalid/gapped market data must not be promoted to research-ready merely to keep pipelines moving.
- Bybit official Spot archives became the approved historical source after the documented LBank quality findings; current repository evidence must be consulted for the latest dataset status.

## 2026-08-07 — Independent backup presence is not recovery proof
Status: ACTIVE

Decision: GitHub remains the authoritative versioned engineering memory. A Google Drive object exists in `NEXUS Project Memory Backup` / `NEXUS Project Memory Backup — Durable`, but it must not be treated as a recovery-valid independent backup until source SHA, content hash, bounded freshness, provider-object binding and privacy/no-secrets controls are verified under Issue #122.

Reason: Provider presence alone cannot prove that the backup matches current repository memory, is untampered, current, privacy-safe, or suitable for recovery. Recovery claims therefore remain fail-closed.

## 2026-08-07 — Release authority remains fail-closed
Status: ACTIVE

Decision: Existing artifact/SBOM/provenance/reproducibility/rollback/backup/DR gates are evidence controls, not production authorization. Signing identity, production approval, credentials, billing, deployment and live financial actions remain outside autonomous authority until separately authorized and verified.
