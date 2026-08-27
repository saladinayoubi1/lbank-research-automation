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
