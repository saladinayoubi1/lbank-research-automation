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

## 2026-08-08 — Current main advanced again; continuity refreshed without relaxing gates
Status: ACTIVE

Evidence: `main` is now `887d50a8de34df4d7f7d4cda38773e43470e7b36` (`data: update LBank public candles`, 2026-08-08T05:27:02Z). The connected exact-SHA surfaces report zero combined statuses and zero PR-associated workflow runs for this SHA. `data/market/_data_readiness.md` on this exact SHA still reports 21 tracked series, 2 research-ready and 19 blocked, with zero duplicate/off-grid observations and integrity failures remaining the blocker. PR #129 pre-update head `e254ee74719547da1aa1ce66b025f664d204d41d` had successful `Test`, `NEXUS Build Verification`, and `NEXUS Cloud Fallback` runs and zero review threads, but its mergeability is currently false after main advanced.

Decision: Keep release and production claims fail-closed under #124 and data consumers fail-closed under #125. Update the existing continuity branch rather than opening a competing memory PR. Do not merge #129 while its current exact head has not been revalidated after this memory update and while mergeability remains false.

Recovery lesson: Rapid direct-main data churn is itself a continuity/release-evidence hazard. A valid PR-head check cannot be reused as evidence for a newer `main`, and a memory update invalidates its own prior head-SHA CI evidence. Always re-query the exact final PR head before merge; keep laptop-offline and internet-outage semantics distinct.

## 2026-08-08 — Bybit execution hierarchy and current-main continuity are now durable
Status: ACTIVE

Evidence: `main` is exactly `44db8d6e6b3797e26bd56d18ec6acb5f529545bc` (`data: update LBank public candles`). PR #130 merged as `e8867307459901df18aaa3e05c7f08947d07e423`, establishing the bounded Data Backfill & Reconciliation Agent contract. Issue #131 records the governed source hierarchy: Bybit is the primary market/execution reference, Binance is the secondary public source for compatible cross-validation and bounded backfill evidence, and LBank is tertiary/research-only.

Decision: Persist this hierarchy without authorizing silent cross-exchange substitution. Unknown or semantically incompatible data remains fail-closed. The current direct-main data commit supersedes the prior transient release snapshot, so release remains blocked until exact-SHA release evidence is independently verified. Production signing, approval, credentials, billing, deployment and live financial actions remain owner-controlled and unauthorized.

Recovery lesson: Architecture decisions and transient repository state are different classes of memory. Durable source hierarchy may be recorded while the exact-main CI state remains unknown; never turn missing verification into a green claim. Refresh the existing continuity PR instead of opening a conflicting memory PR, and preserve laptop-offline versus internet-outage as distinct conditions.
