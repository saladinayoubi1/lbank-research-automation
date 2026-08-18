# NEXUS CHAT HANDOFF — 2026-08-18

## Source of truth
Repository: `saladinayoubi1/lbank-research-automation`
GitHub is authoritative. Do not infer current state from chat history when GitHub can be read directly.

## Authority boundary
Current scope remains **Research / Backtest / Paper only**.
No live orders, private exchange credentials, withdrawals, signing, billing changes, production promotion, or L4 execution.
Deterministic Risk remains final Paper authority.
AI/providers are bounded/advisory and cannot bypass Risk.

## Official phase state
Repository parents confirm:
- Phase 3 #389 — closed / completed
- Phase 4 #510 — closed / completed
- Phase 5 #583 — closed / completed
- Phase 6 #591 — closed / completed
Therefore the current official phase is **Phase 7**, unless Gate 0 later proves a prior phase false-green.

## Phase 7
Parent: **#696 — Unified Intelligence, Strategy Factory, and Realistic Paper Operations**

Four lanes:
1. #697 — AI Control Plane / real dispatch + Resource Manager
2. #698 — Data Intelligence / Regime Engine
3. #699 — Strategy Registry / Factory / Promotion / Drift
4. #700 — Realistic Paper Execution / Reconciliation / Backtest parity

Gate 0 audit: #701
Practical E2E proof mission: **#702**

Required final chain:
`Mission -> Supervisor -> Router/Resource Manager -> Worker -> Evidence -> Independent Verifier -> Canonical Data -> Strategy -> Regime -> Decision -> Deterministic Risk -> Paper -> Performance/Drift -> Mission Control`

## Critical Phase 7 rules
- Resource Manager must allocate **real workload**, not just show ONLINE/OFFLINE telemetry.
- A resource counts as used only with task + lease/fencing + dispatch + result + evidence + verifier.
- **Zero-idle:** if one task waits on CI/I/O/provider/network, dispatch another independent READY task when policy/capacity permit.
- GitHub, Cloud, DeepSeek, internal Agents and the Windows laptop are resources, not the center of NEXUS.
- No fabricated Agent/worker/provider activity.

## Offline Windows laptop
The user's Windows laptop currently has **no internet**.
Gate 0 proved the old Windows worker path depended on GitHub Actions `workflow_dispatch`, so it was not a real offline worker.

P0 implementation is now:
**PR #703 — `Phase 7: add offline laptop dispatch courier`**

Current PR state at handoff:
- state: OPEN
- mergeable: TRUE
- head: `593d31afa9181bf91e7f84397d63f102ef7a24c9`
- base: `07d5bcdda35e23c96c4a34af605b61332c5eb4c8`
- branch: `nexus/phase7-offline-laptop-dispatch`

PR #703 adds:
- offline-courier worker mode for `windows-runner`
- bounded HMAC-authenticated task export -> offline execution -> result import
- lease/correlation/dispatch binding + SHA-256 payload digest
- no fabricated heartbeat
- import through existing `agent_transport.ingest_result()` so stale/spoofed results and independent verification stay authoritative
- durable courier evidence
- regression tests for tamper, stale lease, GitHub bypass, verifier separation

Runtime-only secret boundary:
`NEXUS_OFFLINE_COURIER_KEY`
Never commit it. Missing/short key fails closed.

## Latest CI snapshot for PR #703 head
Exact head `593d31...`:
- Workflow Permissions Policy — SUCCESS
- NEXUS Cloud Fallback — SUCCESS
- Test — SUCCESS
- NEXUS Build Verification — SUCCESS
- Build NEXUS Desktop Windows — SUCCESS
- NEXUS Runtime Worker — QUEUED at last snapshot

Do not claim PR #703 merged until GitHub is checked again.

## DeepSeek
DeepSeek bounded provider infrastructure and hard-cap policy are present.
Do NOT infer current key/provider availability.
For #702, DeepSeek counts as `EXECUTED` only after a real bounded workload returns result/evidence under policy.
If not configured/available, record `UNAVAILABLE` truthfully and continue the rest of NEXUS.

## Product context already delivered
Windows Mission Control 5.0.0 and Android 3.2.0 were previously merged/delivered.
Issue #692 remained open for real product acceptance.
Do not let product UI work displace the four Phase 7 core lanes unless it blocks them.

## Immediate next action in new chat
1. Fresh-check PR #703 and exact-head CI.
2. If all required checks including applicable Runtime Worker evidence are green, merge #703 safely.
3. Continue Gate 0 audit only enough to identify real missing bridges.
4. Start/advance #702 Proof Mission.
5. Prove real workload allocation and zero-idle behavior.
6. For the offline laptop, use the courier path rather than GitHub network dispatch.
7. Do not call Phase 7 complete until one replayable Mission crosses the full chain to Paper/Performance/Mission Control.

## Reporting style
Keep reports compact.
Use 🔴 only for a genuine owner-required blocker.
Do not ask the owner to manually handle engineering problems that can be solved within existing authority.
Do not claim background work or completion without evidence.
