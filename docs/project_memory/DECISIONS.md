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

## 2026-08-08 — Bybit/Binance/LBank source hierarchy is governed by ADR-009
Status: ACTIVE

Evidence: PR #132 merged at exact head `df3b3fa754bfbba93961d13674bf1296c9bc34f9` after `Test`, `NEXUS Build Verification`, and `NEXUS Cloud Fallback` succeeded, mergeability was true, and unresolved review threads were zero. Resulting `main` observed at `7d1ef589310a3f63149ea8a6bb3598a1b0217916`.

Decision: For NEXUS research and paper-trading data architecture, Bybit is the primary market/execution reference, Binance is secondary compatible corroboration/backfill evidence, and LBank is tertiary/research-only. Cross-source data may be reconciled only under explicit semantic compatibility and provenance. No source may be silently relabeled as another exchange; ambiguity, unavailable evidence, open candles, unresolved gaps, checksum/provenance failures, or material disagreement remain fail-closed.

Boundary: This decision authorizes public-data architecture only. It does not authorize live trading, credentials, signing, billing, production deployment, or real financial actions. Implementation remains pending under #131 and must satisfy ADR-009 tests, rollback/recovery, deterministic mapping/manifest contracts, exact-head CI and review gates before merge.

## 2026-08-08 — Source mapping authority now has an executable fail-closed gate
Status: ACTIVE

Evidence: PR #135 merged the ADR-009-aligned Data Backfill & Reconciliation Agent contract at exact head `cfcb397d87dfa22d8b3382c8e7d7b80840cb9668`. PR #136 then merged the source mapping registry, validator and regression suite at exact head `d38185728a58559be13e1efd21ac1a996f2a32b9` after Test, NEXUS Build Verification and NEXUS Cloud Fallback succeeded, mergeability was true, and unresolved review threads were zero. Resulting `main` observed at `005a8c102321121e2e37cf39dc129bd5034ef047`.

Decision: Cross-exchange mapping is deny-by-default. The repository source registry intentionally contains zero approved mappings until instrument/category/timeframe/finality/listing/volume semantics and endpoint contracts are proven. The validator rejects hierarchy changes, silent substitution, live-trading/private-credential authority, unknown fields, ambiguous YAML, invalid UTC/listing semantics, category/role mismatch, duplicate mappings/exchanges, missing Bybit primary evidence and unsupported mappings.

Boundary: This gate does not itself approve Binance/Bybit equivalence, perform network retrieval, mutate datasets, reconcile gaps or authorize live trading. Issue #131 remains open for provenance manifests, evidence-backed mappings, deterministic reconciliation, downstream bypass enforcement and rollback/recovery exercise.

## 2026-08-08 — Architecture contract validation now runs explicitly in Test CI
Status: ACTIVE

Evidence: PR #138 merged at exact head `b2b3e925cce4babf08c630b0629c01eba98ba3c4` after Workflow Permissions Policy, Test, NEXUS Build Verification and NEXUS Cloud Fallback all succeeded, mergeability was true, and unresolved review threads/review submissions were zero. Resulting `main` observed at `4eaadd08c99d4069faa0881707aa8e4a601ee9ac`.

Decision: The existing Ubuntu/Windows/macOS Test workflow must execute `nexus_architecture_validator.py` against the versioned module contract registry before pytest. Validator failure is a delivery blocker and must not be bypassed or weakened to obtain green CI.

Limitation: This proves the validator executes in repository CI; it does not prove independent control-plane protection against a candidate changing the workflow, validator, registry and tests together. Issue #106 remains active and stronger self-authorization claims remain fail-closed.

## 2026-08-08 — One authoritative open Project Memory PR
Status: ACTIVE

Evidence: PR #140 contains the newer repository-owned Project Memory snapshot against current repository evidence; PR #129 is an older continuity snapshot and must not be merged against newer main state.

Decision: PR #140 is the sole authoritative open Project Memory refresh. PR #129 is superseded and must not be merged. Recovery starts from repository Project Memory + STATE + decision log + recovery playbook + exact current PR/CI evidence. A Google Drive object may be treated only as an external backup candidate while #122 is open; presence alone is not recovery evidence and it must not authorize recovery until its versioned contract, freshness, source-SHA/content binding, object identity, no-secrets/privacy checks, replay/substitution rejection and fixed-tuple recovery exercise are verified. Laptop shutdown/offline and internet outage are distinct states and must never be inferred from one another.

Boundary: This consolidation changes continuity metadata only. It grants no signing, production approval, credential, billing, deployment, live-trading or irreversible authority. Drive remains fail-closed and non-authoritative until #122 is satisfied.

## 2026-08-08 — Bounded Binance public Spot adapter merged after replay/window hardening
Status: ACTIVE

Evidence: Review on PR #141 identified that the original exact-head-green implementation trusted the caller interval label and did not prove returned rows belonged to the requested start/end window or a complete deterministic page. The branch was hardened to derive fixed interval duration/grid locally, require explicit request bounds, reject open/incomplete windows, reject oversized single-page requests, bind rows to the requested window, and require the exact expected timestamp set. Regression tests cover wrong granularity, off-grid timestamps, stale/replayed pages, out-of-window substitution, truncated responses and partial-window rejection. On exact head `c6c1fa11edfebbabc1dcfe1992fe6f9c4eebdf2c`, Test, NEXUS Build Verification and NEXUS Cloud Fallback all succeeded, mergeability was true and unresolved review threads were zero. PR #141 then merged, producing `main` `fa5926504e004ba358f14039de0b8a1ab3d85d66`.

Decision: The Binance adapter is approved only as a bounded public Spot retrieval primitive. It proves interval/grid/window/single-page completeness for the supported fixed intervals, but it does not authorize multi-page completeness, source equivalence, real source mappings, reconciliation, dataset mutation or downstream research eligibility. Those remain fail-closed under #131.

Boundary: Public data only; no credentials, persistence, live orders, signing, billing, production deployment or financial action.

## 2026-08-08 — Release recovery validation must observe every main push
Status: ACTIVE

Evidence: Current `main` observed at `87f9e55dd69b76602690d7260fc4d5edca5c1903` has zero combined statuses and no commit-associated workflow evidence on the connected verification surface. `Release Readiness` already subscribes to every `push -> main`, while `Release Recovery` still filters main pushes to recovery-control paths only. Draft PR #144 proposes removing that push path filter without changing its Ubuntu/Windows/macOS matrix or fail-closed tests.

Decision: Production/release claims remain blocked until exact-main evidence is observable on one fixed SHA. A safe prospective remediation is to run the existing Release Recovery gate on every main push so routine direct-main data commits cannot bypass reproducibility/rollback validation by path. PR #144 must remain unmerged until exact-head CI is green, mergeable, review-clean and non-conflicting with newer main.

Boundary: This is CI evidence hardening only. It does not prove reproducible builds, actual rollback, backup/restore, DR, signing, production approval or publisher identity, and it grants no credential, billing, deployment, live-trading or irreversible authority.

## 2026-08-08 — Critical notification marker
Status: ACTIVE

Decision: Any user-facing NEXUS notification that is materially important or requires owner intervention must be prefixed with `🔴`. Routine informational updates that do not require attention should not use this marker. If a critical `🔴` item has not been acknowledged by the owner, the next requested NEXUS report must repeat that item with the same `🔴` marker until it is acknowledged, resolved, or superseded by newer evidence.

Boundary: The marker is presentation/triage metadata only; it does not change severity, authorization, release, production, signing, credential, billing, or financial-action policy.
