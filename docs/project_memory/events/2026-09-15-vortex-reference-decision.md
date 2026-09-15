# NEXUS Memory Event — ATSMATRIX / VORTEX Reference

Date: 2026-09-15
Status: ACTIVE
Type: Architecture / Product-direction decision

## Context
An external ATSMATRIX / ASTRA / VORTEX-style multi-agent trading dashboard was reviewed as a possible reference for NEXUS. Public ATSMATRIX material shows a visually rich multi-agent/market dashboard pattern, but available public code also contains visualization/simulation behavior and does not provide evidence that would justify replacing the NEXUS core architecture.

## Owner decision
NEXUS does **not** require a core architecture rewrite because of ATSMATRIX / VORTEX.

The existing NEXUS direction remains authoritative:
- keep the repository-owned multi-agent architecture;
- keep Bybit as the primary market/execution reference within the existing public-data/Paper-only boundary;
- keep multi-pair, multi-timeframe and multi-strategy operation;
- keep Strategy Factory / strategy discovery, qualification, regime handling and strategy-health lifecycle;
- keep Deterministic Risk as final Paper exposure authority;
- keep the persistent Paper-only trading loop and evidence/replay requirements as the primary mission;
- do not enable Live Trading, private exchange credentials, real orders or automatic Live promotion.

## What may be borrowed from VORTEX-style products
Only presentation and observability concepts are candidates for later NEXUS improvement, especially:
- a stronger real-time Mission Control dashboard;
- clearer visualization of agent status and agent-to-agent relationships;
- Market Stream / event-stream presentation;
- Order Flow / market-state visualization where backed by real validated data;
- unified P&L, strategy-health and portfolio-state views;
- clearer visualization of strategy lanes, decisions, regime, risk and execution state.

These are **UI / monitoring / observability enhancements**, not a replacement trading engine and not a reason to change NEXUS authority boundaries.

## Guardrails
- Do not copy or depend on unverified external trading logic merely because its UI is attractive.
- Do not introduce fabricated/random market values into NEXUS production-quality research evidence.
- Any future VORTEX-inspired UI must consume actual NEXUS state/evidence and must not manufacture trading proof.
- UI work remains lower priority than trading-loop correctness, strategy research quality, Deterministic Risk, Paper lifecycle, performance/drift and required proof, unless the UI directly enables observation or verification of those mission-critical functions.
- External visual references never authorize Live/L4, private credentials, signing, billing, deployment, real financial action or automatic promotion.

## Recovery instruction
When planning future NEXUS UI/Mission Control work, treat ATSMATRIX/VORTEX as a visual/observability reference only. Do not reopen or redesign the NEXUS core solely to imitate that product. Preserve the current mission lock and build visual improvements on top of verified NEXUS data and agent state.
