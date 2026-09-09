# NEXUS Project Memory

## Purpose
This directory is the durable, repository-owned memory for NEXUS. Chat history is not a source of truth. Any agent must read this memory before planning or changing the project.

## Immutable mission and safety boundary
- Research automation, public market-data collection, validation, backtesting and paper-forward research only.
- No real trading, order placement, deposits, withdrawals, private exchange credentials or financial-account control.
- Never fabricate candles or silently repair/clamp source OHLC.
- Backtests must not pass invalid/gapped data as valid.
- Main-branch changes should pass review/CI; sensitive or irreversible actions require explicit human approval.

## Mission Lock — primary delivery objective
The primary delivery objective is a continuously operating **Paper-only trading engine**, not UI, packaging, proof infrastructure, or agent infrastructure by themselves.

The engine must continuously execute the complete portfolio loop:
`Public canonical market data -> multi-pair -> multi-timeframe -> multi-strategy -> regime -> qualification -> allocation/decision -> Deterministic Risk -> Paper open/close/rebalance -> performance/drift -> strategy health/lifecycle -> Strategy Factory discovery/requalification -> next closed-candle cycle`.

Required operating model:
- Multi-pair portfolio operation; BTCUSDT/ETHUSDT are the current verified base, with the architecture remaining extensible to additional approved pairs.
- Multi-timeframe operation; minute15/hour1/hour4 are the current required synchronized timeframes.
- Multi-strategy operation; momentum/trend_breakout/mean_reversion are the current base families and Strategy Factory must continue bounded discovery of new research proposals.
- Every `symbol x timeframe x strategy` lane is independently evaluated before portfolio allocation.
- Regime and strategy health may reduce allocation to cash; CASH/REJECT/NO_ACTION are valid outcomes and must never be replaced by fabricated trades.
- Deterministic Risk remains the final execution authority for Paper exposure.
- Paper execution must model lifecycle, fees, slippage, partial/complete fills where applicable, reconciliation and PnL evidence.
- Performance/Drift must feed strategy health/lifecycle and future selection without allowing automatic Live promotion.
- Strategy discovery must continue even when the current portfolio is 100% cash or no current proposal qualifies.

### Work-priority rule
Until the persistent end-to-end trading loop above is verified operational, material work must be prioritized in this order:
1. Trading-engine loop correctness, persistence and autonomous closed-candle operation.
2. Strategy research/discovery/qualification quality and multi-pair/multi-timeframe portfolio behavior.
3. Deterministic Risk, Paper lifecycle, performance/drift and replayability.
4. Evidence/verification required to prove the trading loop.
5. UI/mobile/packaging/installer/agent infrastructure only when it directly enables, observes or verifies items 1-4.

Supporting work must not displace the trading engine merely because it is easier to complete or produces green CI. A green build, installer, app, workflow or proof harness is not equivalent to completing the trading objective.

Before starting a material task, the acting agent must be able to state its direct mission link. If no direct link exists, defer/reject the task unless the owner explicitly changes priority. Core mission changes require explicit owner direction and must be recorded in Project Memory.

Canonical machine-readable lock: `config/nexus-mission-lock.json`.

### Completion rule
Do not claim the NEXUS trading core is complete until repository/runtime evidence proves the persistent loop operates end-to-end across the required pairs, timeframes and strategy families, accepts valid cash/no-action outcomes, keeps Deterministic Risk final, feeds genuine Paper outcomes into Performance/Drift/Strategy Health, continues bounded Strategy Factory discovery, and restarts/replays without inventing evidence.

## Autonomy objective
Build NEXUS incrementally into a resilient, largely self-operating development/research system that can plan bounded work, detect failures quickly, retry/recover safely, preserve learned solutions, and escalate only when a decision exceeds its authority.

Autonomy must be granted in layers. New authority starts narrow and low-risk. Core goals and safety boundaries are not automatically editable by agents.

## Durable-memory contract
1. Before work: read this file, `STATE.json`, `DECISIONS.md`, and `RECOVERY_PLAYBOOK.md`, then enforce `config/nexus-mission-lock.json` when selecting material work.
2. During work: use repository/CI/runtime evidence rather than chat recollection.
3. After a material event: append a concise decision/lesson and refresh state.
4. Never store secrets, API keys, tokens, passwords, private account data, or raw sensitive chat content here.
5. Prefer facts and decisions over verbatim conversation transcripts.
6. Every important entry should identify date, evidence/commit/issue/PR when available, and whether it is active/superseded.
7. If memory conflicts with current repository evidence, stop automatic high-impact action, record the conflict, and resolve from authoritative evidence.

## Current architectural anchors
- GitHub repository is the durable engineering source of truth.
- Fast Agent Coordinator and local supervisor provide rapid status/recovery while the laptop is available.
- Cloud fallback must remain independent of laptop uptime where possible.
- Project memory must remain useful even if a ChatGPT conversation, local browser session, or local machine state disappears.
- External model workers such as DeepSeek are optional accelerators, never a single point of failure and never owners of secrets/merge/release authority by default.

## NEXUS AI Council / AI Room
The AI Council is a durable NEXUS architecture component and must be recovered by every new chat/agent together with the rest of Project Memory.

Canonical implementation:
- `scripts/nexus_ai_council.js`
- `config/nexus-ai-council.json`

Current policy version: `1`.
Current quorum: `2`.
Current roles:
- `stability` — priority 1, veto enabled;
- `security` — priority 2, veto enabled;
- `delivery` — priority 3, no veto.

Current decision behavior:
- invalid/unknown votes are ignored;
- insufficient valid votes => `defer`;
- a rejecting veto role can reject when `rejectOnVeto` is enabled;
- otherwise majority decides;
- ties use the lowest numeric role priority as tie-breaker.

Operational intent:
- The AI Council is a bounded review/decision layer, not the primary scheduler and not a replacement for Product/Research execution.
- It may combine independent AI/agent perspectives for stability, security and delivery decisions.
- It must not own credentials, billing, live trading, production, signing, irreversible actions, or unrestricted merge/release authority.
- DeepSeek and other external models may contribute bounded advisory analysis but do not gain veto/authority merely by participating.
- Council review must not silently expand an active phase. A stability/security concern may block the active delivery objective only when it concretely invalidates a frozen acceptance gate; otherwise it belongs to backlog/next phase.
- The Council must not cause idle time: when one reviewed item waits on CI/runner/external evidence, independent Product/Research/Strategy work that advances the Mission Lock continues.
- Council existence, policy, role configuration and meaningful policy changes must be persisted in Project Memory and checked during chat migration/recovery.

## Continuity rule
A fresh agent/session should be able to recover direction by reading this directory plus repository history, issues, PRs and CI. If it cannot, the memory system is incomplete and must be repaired before increasing autonomy.

## Current verified operational checkpoint — 2026-09-09
Exact-main run `34392341610` on source `57f0c4156722fad47125f8e92e66465ee207260a` completed every Multi-Pair Discovery v2 job successfully. The physical WSL runner restored a hosted exact-source artifact without JavaScript actions or Git fetch, reused the shared wheelhouse only after deterministic repack/digest/lock/symlink validation, verified the official Bybit archive snapshot, acquired a fresh 12-cell runtime snapshot on the same physical plane, relayed it to hosted artifact persistence without Node on WSL, and completed physical requalification plus hosted proof persistence. The valid result was `NO_WORK` with zero Research proposals; zero work does not authorize fabricated proposals or automatic promotion.

The earlier 8/12 Paper failures were a workflow-contract defect, not proof of a Bybit data-plane outage: freshness is bound to the current source SHA, so after a main change the four `hour4` cells correctly remain `SKIPPED_NO_NEW_BAR` until the next naturally completed four-hour boundary while the eight shorter-timeframe cells advance. PR #1418 retained exact 12/12 acceptance for `PAPER_LOOP_ACTIVE` and accepts `WAITING_FOR_FRESH_CELLS` only after engine plus independent workflow verification confirms the below-12 count, waiting mission gap, and inactive maintenance/regime/exposure/health-trigger outputs. Exact-main run `34397395277` succeeded at 8/12 and durably persisted artifact `10122430632` (`sha256:d18e52bc11c56cba6d4332c9b3681bf54b95478572bdeb8deafbe7a33f45cad6`). Endpoint HTTP 403 diagnostics were observed, but successful fallback and the deterministic four-cell pattern show they were not the root cause of 8/12. Issue #984 remains independent, open and immutable at 89/180 bars and a 14/30 elapsed-day floor. All authority remains Research/Backtest/Paper only; Deterministic Risk remains final and Live/private-credential/real-order/automatic-promotion authority remains false.

## Strategy Factory replay-v2 checkpoint — 2026-09-09
PR #1421 registered Multi-Pair Discovery v2 as the eighth reviewed Strategy Factory stage. PRs #1422 and #1424 then removed expired fixed replay-artifact coupling from the Demo lifecycle bridge and seven legacy Strategy Factory workflows. Replay input is now selected from unexpired prefix-matching artifacts and independently bound to the exact replay filename, delivery manifest, zip payload, embedded manifest, and canonical semantic dataset SHA-256 `2455a725886d81adaec9d3478e8f3b2daaba6c0c9645a691e71737eb64f67422`; an optional artifact ID only narrows candidates and never bypasses validation.

On exact main `50ac6ea8a331c08dca3e8be184ed0717380ff7f6`, Demo lifecycle run `34404429298`, search-v2 run `34404244591`, Multi-timeframe run `34404244665`, regime-v6 run `34404358221`, neighborhood-v7 run `34404651563`, and rotation runs `34404244680` / `34404548937` all succeeded. The controller verified 8/8 ready stages and advanced the durable cursor to index 6 without claiming qualification authority. Neighborhood v7 passed its frozen-strategy and parameter-plateau gates with 29 dual-profile passers and reported eligibility for derivatives validation and prospective Paper-forward review, but `automatic_paper_forward_started=false`.

This positive research result is a human-review boundary, not promotion. Artifact `10125093054` must be independently reviewed before any bounded derivatives validation or prospective Paper-forward admission is authorized. No automatic promotion, Issue #984 mutation, Live/L4 authority, private credentials, or real exchange orders are permitted. Deterministic Risk remains final.

## Multi-Pair Paper feedback runtime checkpoint — 2026-09-09
Exact-main feedback run `34412163303` correctly resolved and digest-bound its Paper and Discovery v2 evidence, then failed closed because its isolated job had not provisioned the locked runtime dependency set required by the Paper snapshot verifier. PR #1430 added pinned Python 3.12, `requirements.lock`, and `pip check` to that exact job, plus regression coverage requiring provisioning before verifier import. All exact-head policy, target-workflow, Test, Build Verification, and Cloud Fallback checks passed before merge.

On exact main `21af398b9e73896f98c792a99230cf1562f7a04b`, Paper run `34413401197` persisted a verified 4/12 `WAITING_FOR_FRESH_CELLS` artifact `10128322177` (`sha256:b82b4ee02ae271cf13d0ba0dd4cac2d793646e52827aa8043728fd109ad5a98d`). Multi-Pair Discovery v2 run `34413429714` then completed all seven jobs with zero Research proposals, a fresh distinct 12-cell runtime snapshot, `NO_WORK` requalification, and proof artifact `10128592404` (`sha256:776a1bd95e8742352e50067cac1302a64fc90bdd064b0b90cef4fa1b3b93206d`). Automatic feedback run `34414723066` passed locked dependency provisioning, exact-SHA pair resolution, and both artifact-binding checks, then correctly emitted `NO_OP_NOT_ELIGIBLE` because the natural 12-cell Paper health boundary was not reached.

The repaired feedback path links evidence only when the exact natural boundary is eligible; it does not fabricate cells or create Candidate/Paper promotion. No feedback artifact was emitted for the no-op. Issue #984 was not touched, Deterministic Risk remains final, and Live/L4, private credentials, real exchange orders, signing, deployment, and automatic promotion remain unavailable.
