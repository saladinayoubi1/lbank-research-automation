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

## 2026-08-24 — Verified integration chain now reaches Mission Control
Status: ACTIVE

Evidence: PRs #954, #955, #956, #957 and #958 merged sequentially. Current `main` is
`e3e03642c40bb0543dd5e6d92290472f7a5d5961`. The merged chain registers and validates
the component graph, keeps the AI Room proposal-only, verifies bounded execution with
producer/verifier separation, connects Supervisor output to Strategy and isolated Paper,
evaluates deterministic performance drift/quarantine, and projects validated closed Paper
trades into a digest-protected Mission Control read model.

Decision: Treat the integration chain through Mission Control as repository-verified.
Do not treat green CI, registration, heartbeat, an unclosed Paper position, or a detached
analytics record as proof of resource use or strategy performance. Remaining acceptance is
the fixed-SHA end-to-end Proof Mission plus evidence that the autonomous-improvement loop
can propose and verify bounded changes without expanding authority.

Boundary: Research/Backtest/Paper only. Live Trading, private exchange adapters,
credentials, signing, billing, deployment, production promotion and self-authorization
remain unavailable.

## 2026-08-25 — Final Proof Mission requires physical Windows execution
Status: SUPERSEDED by the later 2026-08-25 verified-completion decision below

Evidence: PR #959 reconciled Project Memory with the verified integration chain. PR #960
added the fixed-SHA final Proof Mission verifier. PR #961 then corrected the acceptance
contract so a truthful `UNAVAILABLE` or `BLOCKED` Windows declaration remains useful
diagnostic evidence but cannot produce a `VERIFIED` final decision. Current observed
`main` is `ec203f83bf81ca7953ef812e535a9ef23591c3a8`.

Decision: The remaining convergence path is durable evidence, not another architecture
rewrite: assemble Supervisor, Mission-Control, scheduler, resource-utilization, and
canonical Project-Memory evidence on one source SHA; require the Windows laptop to have
an actual task/lease/result/evidence/verifier chain; run the independent verifier; then
persist the verified result. DeepSeek remains optional and must be classified truthfully
as `EXECUTED` or `UNAVAILABLE`.

Boundary: The assembler is data-only and cannot manufacture missing resource use. The
result remains Research/Backtest/Paper-only and grants no Live/L4, private-credential,
signing, billing, deployment, production-promotion, or self-authorization authority.

## 2026-08-25 — Final Proof Mission completed and independently verified on physical Windows
Status: ACTIVE

Evidence: Session `p7-20260825T091334Z-8a56bfb0` was prepared from exact source SHA
`36a3d64f6ce3253b2f9ca76eb594c6afe80e4e9c`. Data-only return PR #966 used head
`822716834f440e9601bc1f4276d72cb8ff486e47` and was closed unmerged as designed. Mission
Queue run `32833291451` independently verified the returned package and published artifact
`nexus-phase7-return-verified-p7-20260825T091334Z-8a56bfb0` (artifact ID `9557615766`,
digest `sha256:113b9b768aeae823c068892b392c959c4a2d32d06d596948eb6c2bf11ba612aa`).
The verifier recorded a real reboot after preparation, internet unavailable before and after
offline execution, `hardware_proof_complete=true`, `core_cloud_chain_complete=true`, 100%
verified progress, Laptop/Internal Agent/Cloud classifications `EXECUTED`, zero-idle overlap,
and DeepSeek truthfully `UNAVAILABLE` with reason `provider_budget_gate_closed`. Paper-only
remained true and live-trading authority false. PR #967 then hardened PowerShell 5.1 session
bookkeeping without changing runner/watchdog state or authority. PR #972 repaired the
wrapper/core regression-test surface; its exact head passed Workflow Permissions Policy,
NEXUS Mission Queue, NEXUS Cloud Fallback, Test, and NEXUS Build Verification before merge.

Decision: The physical-Windows acceptance requirement in the preceding decision is
satisfied and superseded. No further Phase 7 physical proof is required for this acceptance.
Treat the final Proof Mission as completed evidence for the bounded Research/Backtest/Paper
architecture. Provider unavailability is not to be disguised as execution, and subsequent
maintenance must preserve the wrapper/core security, offline, data-only-return, and
producer/verifier separation invariants. Do not reintroduce self-heal/watchdog behavior as
part of this completion bookkeeping.

Boundary: This completion does not grant Live/L4, private exchange credentials, signing,
billing, deployment, production promotion, destructive authority, or self-authorization.
The verified Google Drive continuity mechanism remains secondary-only and must be refreshed
against the final canonical memory snapshot before it is described as current.

## 2026-08-25 — Final Project Memory Drive refresh verified against final Proof snapshot
Status: ACTIVE

Evidence: After PR #973 merged, the durable Google Drive document `NEXUS Project Memory Backup — Durable` was refreshed in place against exact repository source SHA `6d84d1003666cc8fd9bb86f9aea203b459574b54`. Provider revision `3` was read back as a text/plain export of 56,782 bytes with raw SHA-256 `8904567e289d113435b5e32e89f559a018e7435b9acd147c5cc67e3305dcadd4`. All seven canonical Project Memory file contents matched their current Git blob IDs exactly. Privacy scanning returned zero forbidden findings. The verification manifest is Drive object `1TtbOxGPpelKbMYmDFn6_w8x-wwkqHv7X`, with byte SHA-256 `2d7bb0744866a491a41253d20241abcb1892066fecd9abd7e7df05d340b22296` and canonical manifest digest `b9e986f485ad0b8046749a42603ff70144667c963b020fe598c08317ce18342d`. Issue #122 comment `5411422131` records the fixed tuple and adversarial recovery checks.

Decision: Treat the Drive document/revision above as the verified secondary recovery snapshot for the final Proof Mission memory state at source SHA `6d84d1003666cc8fd9bb86f9aea203b459574b54`. Preserve repository Project Memory as primary authority. Future material memory changes must refresh and re-verify the secondary snapshot rather than silently treating this tuple as current forever.

Boundary: Secondary continuity only. This evidence does not authorize production recovery, signing, private credentials, billing, deployment, Live/L4, financial actions, destructive operations, or self-authorization.

## 2026-08-25 — Frozen Bybit candidate entered prospective Paper collection
Status: ACTIVE

Evidence: PR #976 connected the completed Phase 3 task surface to the bounded Bybit strategy-search ladder, and PR #977 made the reviewed v2 search contract event-driven without changing qualification authority. Neighborhood run `32900398896` / artifact `9582995776` qualified the frozen candidate, and derivatives run `32901089264` / artifact `9583168864` qualified it for prospective Paper. PR #978 merged the digest-protected Paper-forward lane for strategy `bybit_btc_eth_regime_consensus_v1`, bound to frozen manifest SHA-256 `2a5486eb1f77ce199cac77d280d59d5fa11fa2bcd4ae8091264f78e21f45c19d`. Its first main run correctly exposed a pre-cutoff empty-window defect. PR #982 fixed that bounded initialization path at exact head `f0abc0131915e60a7c56ecd4899feccc6c7b42dd` after all five required checks succeeded, and squash-merged as `ca2b3f284dd2a6fd910dd25a86e8025ba490fa20`. Main run `32905463932` then succeeded and published artifact `9584635133` with state digest `a30332e039e5a27342018b1be111b901c7a6df2b975234fc282d140cc2a2d283`, status `COLLECTING`, zero completed prospective bars, Paper-only true, Live false, automatic Live promotion false, and private credentials unused.

Decision: Treat Phase 3 as closed and do not reopen it. Treat the separate prospective Paper lane as active evidence collection, not as strategy approval or completion. It must accumulate at least 30 days and 180 completed four-hour bars before a review-required outcome; tampering, engine/manifest drift, invalid public data, or risk-bound violations remain fail-closed. The previously verified Google Drive snapshot at source SHA `6d84d1003666cc8fd9bb86f9aea203b459574b54` is now stale relative to repository memory and must be refreshed and independently re-verified before being described as current.

Boundary: Research/Backtest/Paper only. No exchange orders, private credentials, Live/L4, signing, billing, deployment, production promotion, destructive authority, or self-authorization.

## 2026-08-26 — Drive secondary snapshot refreshed after active Paper reconciliation
Status: ACTIVE

Evidence: After #983 materially advanced canonical Project Memory, the earlier source-`6d84d100` refresh candidate was not merged as current; PR #985 was closed unmerged. A replacement canonical seven-file snapshot was generated from exact source SHA `4a662fe0eb62f5de4f5765d6b10c1bc6daa53908` by workflow run `32944825655` (artifact `9597841242`). It was stored in a new private Google Docs object `13LOcKDtB7Ji_-qxyyUcd0Cy6zVO9raW3NBkKxsh6TKc`, revision `1`, modified `2026-08-26T07:52:34.916Z`, preserving earlier verified objects as legacy evidence. Provider `text/plain` export is `63079` bytes with raw SHA-256 `898ffb5d0d0a4f5222dcc8552fed36fb7b735e64d660555306243656b885d6ae`; the canonical snapshot is `63063` bytes with SHA-256 `348ac4de0a613a06fe9d66ba8a8862e073301d20a76df372598ec09161127ff1`. The bounded Google Docs adapter confirms provider JSON equals the canonical snapshot. Manifest digest is `d5c806b870a3d8cfb3f5d133a79c8d221de458c2ca79eabdba2cdca722744270`; the manifest is stored as Drive object `1DFIjFDyImgLnKgyNQy5flPDxK_lMpv8I` with file SHA-256 `83fa25bef1e4b3edc538b610abaa4c40796402be12a4f89f264cc3eeed493f7d`. Privacy findings are zero; object, revision, source-SHA, name and content substitutions all fail closed.

Decision: Treat this fixed tuple as the current secondary Project Memory recovery candidate as of source SHA `4a662fe0eb62f5de4f5765d6b10c1bc6daa53908`. Repository Project Memory remains authoritative. Any later material Project Memory change makes this tuple stale until a new provider refresh is verified.

Boundary: Secondary continuity only. No Production/Live/L4, credentials, signing, billing, deployment, financial action, destructive authority, watchdog/self-heal, or self-authorization is granted.
