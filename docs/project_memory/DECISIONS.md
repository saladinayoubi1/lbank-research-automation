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

Boundary: This gate does not itself approve Binance/Bybit equivalence, perform network retrieval, mutate datasets, reconcile gaps or authorize live trading. Issue #131 remains open for the public Binance adapter, provenance manifest, evidence-backed mappings, deterministic reconciliation, downstream bypass enforcement and rollback/recovery exercise.

## 2026-08-08 — Architecture contract validation now runs explicitly in Test CI
Status: ACTIVE

Evidence: PR #138 merged at exact head `b2b3e925cce4babf08c630b0629c01eba98ba3c4` after Workflow Permissions Policy, Test, NEXUS Build Verification and NEXUS Cloud Fallback all succeeded, mergeability was true, and unresolved review threads/review submissions were zero. Resulting `main` observed at `4eaadd08c99d4069faa0881707aa8e4a601ee9ac`.

Decision: The existing Ubuntu/Windows/macOS Test workflow must execute `nexus_architecture_validator.py` against the versioned module contract registry before pytest. Validator failure is a delivery blocker and must not be bypassed or weakened to obtain green CI.

Limitation: This proves the validator executes in repository CI; it does not prove independent control-plane protection against a candidate changing the workflow, validator, registry and tests together. Issue #106 remains active and stronger self-authorization claims remain fail-closed.
