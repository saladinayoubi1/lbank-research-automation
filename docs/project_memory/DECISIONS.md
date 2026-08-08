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

## 2026-08-08 — LBank historical gaps remain fail-closed
Status: ACTIVE

Evidence: `main` at `914c8e3d70fe598407f4e7e2b06a6152b74d5015`, `data/market/_data_readiness.md` evaluated `2026-08-07T20:23:51Z`, blocker #125.

Decision: 19 of 21 tracked LBank symbol/timeframe series are not research-ready because historical continuity checks fail. Current freshness is within policy and duplicate/off-grid counts are zero, so the active blocker is persistent historical gaps, not present collector staleness. Only `aero_usdt/hour4` and `agt_usdt/hour4` are currently ready.

Policy: Keep all affected series excluded from Backtest, Strategy Lab, Decision Engine and Paper Trading. Missing intervals remain `unknown/unavailable` until deterministic reconciliation proves that an approved public source exposes the candle. Never fabricate/interpolate candles or silently mix exchange namespaces to make integrity green.

## 2026-08-08 — Every main push requires traceable release-readiness evidence
Status: ACTIVE

Evidence: PR #128 merged into `main` as `069c54e0ba9b5dd4df89a29567b96fb9688e1be3`. The release-readiness workflow now subscribes to every push to `main`. On the currently available verification surface, combined status for the exact main SHA is empty and commit-associated workflow lookup exposes no run; that lookup is PR-event-limited, so absence is not proof that a push-triggered run did not execute.

Decision: Release authority remains fail-closed until CI evidence can be independently observed and bound to the exact candidate main SHA. A workflow trigger configuration is prospective control, not evidence that a particular main commit passed. Issue #124 remains the release blocker.

Operational rule: Repository-managed data, code, schema and workflow changes should flow through branch/PR review or an explicitly reviewed equivalent control that preserves immutable exact-SHA evidence. Repeated direct `data: update LBank public candles` commits on `main` remain a provenance/change-control gap until that path is governed.

## 2026-08-08 — External Drive copy is continuity aid, not recovery proof
Status: ACTIVE

Evidence: Google Drive folder `NEXUS Project Memory Backup` and document `NEXUS Project Memory Backup — Durable` are present; the latest observed document snapshot mentions current main `069c54e0ba9b5dd4df89a29567b96fb9688e1be3` and preserves the no-secrets and laptop-offline/internet-outage distinction.

Decision: The Drive document is an independent continuity copy only. It must not be promoted to recovery-proven, tamper-resistant, privacy-verified, or production-authoritative evidence until #122 proves source-SHA binding, content hash, freshness contract, provider-object binding, no-secrets/privacy validation and recovery exercise behavior.

Rollback/recovery: Preserve the previous-known-good repository memory and Drive copy when validation fails. Quarantine stale, conflicting or unverifiable candidates instead of overwriting known-good continuity evidence.

## 2026-08-08 — Direct main data commit advanced continuity state without traceable CI
Status: ACTIVE

Evidence: `main` advanced to `c8643f428cbe46df264da934c7aa36c31acf09e7` with commit `data: update LBank public candles`. On the available verification surface, combined status is empty and commit-associated workflow lookup returns no run for this exact SHA.

Decision: Treat this SHA as a material continuity event but not as release-ready. Keep production/release fail-closed under #124, and continue treating direct repository-managed data commits to `main` as a provenance/change-control gap until the data update path is routed through branch/PR review or a reviewed equivalent control with exact-SHA evidence.

Recovery lesson: A workflow configured for `push` is not sufficient evidence by itself; recovery and release decisions must bind to observable evidence for the exact candidate SHA. Preserve the distinction between laptop offline state and internet outage when reconstructing operational state.

## 2026-08-08 — Repeated direct-main data updates invalidate transient release evidence
Status: ACTIVE

Evidence: `main` advanced again to `1f0f42dde56ec5a363f3120e22a6a721ea8af88c` at `2026-08-08T03:44:32Z` with `data: update LBank public candles`. For this exact SHA the available combined-status surface returns zero statuses and the commit-associated workflow lookup returns zero runs. The latter lookup is PR-event-limited; therefore absence alone does not prove a push run did not execute. The `Release Readiness` workflow configuration still subscribes to every push to `main`.

Decision: This exact main SHA is not release-ready on currently observable evidence. Keep release/production fail-closed under #124. Refresh the existing continuity PR #129 rather than creating a conflicting memory branch. The independently stored Drive continuity snapshot may record this fact, but it remains non-authoritative for recovery until #122 is satisfied.

Recovery lesson: Recurring direct-main data commits repeatedly supersede exact-SHA release evidence and stale transient project-memory state. The durable fix is to route the data producer through branch/PR review or a reviewed equivalent mechanism that preserves immutable exact-SHA CI/provenance evidence; do not weaken release or data gates to accommodate the current direct-main path.
