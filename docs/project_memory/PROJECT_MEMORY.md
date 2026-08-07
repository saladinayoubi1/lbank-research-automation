# NEXUS Project Memory

## Purpose
This directory is the durable, repository-owned memory for NEXUS. Chat history is not a source of truth. Any agent must read this memory before planning or changing the project.

## Immutable mission and safety boundary
- Research automation, public market-data collection, validation, backtesting and paper-forward research only.
- No real trading, order placement, deposits, withdrawals, private exchange credentials or financial-account control.
- Never fabricate candles or silently repair/clamp source OHLC.
- Backtests must not pass invalid/gapped data as valid.
- Main-branch changes should pass review/CI; sensitive or irreversible actions require explicit human approval.

## Autonomy objective
Build NEXUS incrementally into a resilient, largely self-operating development/research system that can plan bounded work, detect failures quickly, retry/recover safely, preserve learned solutions, and escalate only when a decision exceeds its authority.

Autonomy must be granted in layers. New authority starts narrow and low-risk. Core goals and safety boundaries are not automatically editable by agents.

## Durable-memory contract
1. Before work: read this file, `STATE.json`, `DECISIONS.md`, and `RECOVERY_PLAYBOOK.md`.
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

## Continuity rule
A fresh agent/session should be able to recover direction by reading this directory plus repository history, issues, PRs and CI. If it cannot, the memory system is incomplete and must be repaired before increasing autonomy.
