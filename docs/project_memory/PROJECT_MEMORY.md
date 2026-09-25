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

## Windows self-hosted runner recovery checkpoint — 2026-09-10
PR #1433 removed ambiguous Windows self-hosted routing by binding Local jobs to `nexus-local` and DR jobs to `nexus-remote-rescue`. On exact main `91b29b36e38eeb03c45bf52060030fa940206b81`, both Windows runner installations were migrated from an incomplete GitHub Runner `2.336.0 -> 2.337.0` self-update state to the standard junction layout where `bin` and `externals` target the staged `2.337.0` directories. No runner registration or credentials were replaced.

Exact-main DR Persistence run `34482923984` completed successfully on `NEXUS-WINDOWS-DR`, including the exact-target persistence validation, and persisted artifact `10156147936` (`sha256:e39caa5ccb230078e434059efed66859d5338ae33b5739ea5751c55db3d89a54`). Exact-main Local Autonomy run `34482924040` then completed every job step successfully on `NEXUS-LOCAL-RUNNER`, including exact SHA verification, bounded autonomous queue execution, durable-state evidence and artifact upload; artifact `10157084959` has digest `sha256:69665a8e68ea02eb0971380425f296bdde8910d4eac4bc90fca67fbe70a0d955`.

After both proofs, `NEXUS-BYBIT-WSL`, `NEXUS-LOCAL-RUNNER`, and `NEXUS-WINDOWS-DR` were all observed `online` and idle with their role-specific labels. Treat the routing/Windows update incident as operationally closed unless new repository or runner evidence shows a regression. Issue #984 remains independent at the last verified 89/180 completed four-hour bars and 14/30 elapsed-day floor; no Live/L4, private-credential, real-order, signing, deployment, or automatic-promotion authority was created.


## Exact-main desktop activation and prospective Paper 180/180 checkpoint — 2026-09-25
PR #1803 fixed token-aware UI status semantics so negative compound states such as `inactive`, `unverified`, and `not_ready` cannot be rendered green by positive substrings. Its exact head passed the full cross-platform Test workflow, Build Verification, audit, secure-gateway, fallback-health, and control-plane checks before squash merge as main `804a81119cf224de3397aa0a88fca75d18b25126`.

Build Verification run `36087959492` succeeded on that exact main. Persistent Windows artifact `10844033352` is bound to outer digest `sha256:a313fd8441db3c0e852edac6ff72993575dbdae0814d5c881fcbe09e89c5a76d` and unpacked package SHA-256 `96bbed17886635feb419bd216666061ceb776d6c94aa53f3a5bdc426c392f622`. Physical fastpath run `36088426787` then passed exact-source validation, codeload source restore, preloaded cache verification, install/smoke, and physical proof on `NEXUS-LOCAL-RUNNER` / `DESKTOP-1R1081M`. The active desktop and sidecar processes point to `5.1.0-804a8111`. Runtime APIs report Mission Control `clean_install_idle`, Paper active, and Live disabled; live orders, withdrawals, and production promotion remain denied. `NEXUS-BYBIT-WSL`, `NEXUS-LOCAL-RUNNER`, and `NEXUS-WINDOWS-DR` were all observed online and idle.

The independent prospective Paper gate #984 is now verified at `180 / 180` completed four-hour bars from producer run `36078163210`, artifact `10840950765`, state digest `0d00b8bae995e468d19410724729078d3fa59c56cc5e20a3b557ad02cbdd5eb1`, and tail event digest `b4398156835b9c83aa428b60498780bde74da5489889c160d5368ebdf399a3d2`. It remains correctly `COLLECTING` because the represented interval from `2026-08-26T00:00:00Z` to `2026-09-24T20:00:00Z` is 29 days 20 hours. The next real observation at `2026-09-25T00:00:00Z` cannot become a closed 4h observation until after `2026-09-25T04:00:00Z`. Do not synthesize, backfill, or infer that observation. A terminal outcome still requires canonical producer evidence plus independent state/event/runtime-attestation verification.

Authority remains Research/Backtest/Paper only. Deterministic Risk remains final. Live/L4, private exchange credentials, real exchange orders, withdrawals, signing, deployment, production promotion, and automatic strategy promotion remain unavailable.

## Terminal prospective Paper result and bounded desktop retention — 2026-09-25
Current exact main is `77d23868ded3cccc291db2d8b28b6ee4030e8b00` from PR #1809. Build Verification `36092111087` succeeded; persistent Windows artifact `10845687916` is bound to outer digest `sha256:b8b5ef168f27c16afe02652c897b7a8b8d436346d097a3b36a144eead2f0276b` and unpacked SHA-256 `131a18c19c48eae49c3f5d5c382f448140ada634efd2e780a170e53623d3f3a9`. Physical fastpath `36092850848` passed source/cache/install/smoke/activation proof on `DESKTOP-1R1081M`, activated `5.1.0-77d23868`, and bounded verified rollback retention to three directories: current `77d23868` plus `804a8111` and `ee41a1a5`.

The prospective gate then completed. Canonical run `36093393527` advanced the chain to 181 four-hour bars through `2026-09-25T00:00:00Z` and terminal `QUARANTINED` / `paper_forward_failed_no_promotion`. Independent reporter `36093483606` re-verified exact artifact/runtime evidence and updated #984. Both conservative and stress profiles had 3 fills against the locked minimum 4; all observed return, drawdown, asset-fill, funding, execution, margin, risk-tier, rejection and liquidation checks otherwise remained inside their locked limits. #984 is closed `not_planned`; the candidate is not promotable.

Authority remains Research/Backtest/Paper only. Live/L4, private credentials, real exchange orders, withdrawals, signing, deployment, production promotion and automatic strategy promotion remain unavailable. The next technical priority is a new bounded Strategy Factory candidate, not weakening the failed gate.
## Post-quarantine execution-integrity and new-candidate checkpoint — 2026-09-25

The prior prospective #984 candidate completed 181 genuine four-hour observations and the 30-day condition, but remained terminal `QUARANTINED`: 3 fills against the locked 4-fill minimum in BOTH conservative and stress. The immutable producer was `36093393527` and the independent reporter `36093483606`; #984 is closed `not_planned`. PR #1812 made the independent reporter expose the exact failed locked criteria without relaxing them. Neither a simulator correction nor a historical research success can retroactively promote this failed candidate.

PR #1813 (`aa6b87be768d5ba4125270d70bec13b44287c1ff`) fixed fee-funded phantom rebalancing fills in the shared binary long/flat Multi-Timeframe/Multi-Pair research executor; a static flat-price long previously recorded 6 fills instead of the genuine entry and terminal exit (2). PR #1816 (`6e1b27eb0f017e71844e5f0408b0355e93f392ef`) additionally preserves positive residual capital on unexecutable dust entries. The intervening exact-main MTF run `36101958735` failed with invalid zero equity; **the complete corrected real main MTF run `36103201556` succeeded**, including exact archive restoration, base search, bounded training-only refinement, fail-closed authority verification, and a new exhaustion certificate. Its immutable full artifact is `10850451545` (`sha256:96e4cefad041a39242d289b7b87504ff8275abf07205c6f182821b4fe4ad010b`); exhaustion artifact `10850546396` (`sha256:394b77b11893dece7dc3d518521a9bd43cdafe580d267bc806b5fc0decb312e6`), certificate digest `67f6de7d00de39180a10a0c0aa4893f2c20cdd386a6a6be39233f9f928ba6a73`. Both 9-cell base and refined historical searches returned zero research proposals. In the base selected conservative historical checks, all nine cells failed drawdown, minimum Sharpe, positive ratio, and worst return, despite nonzero fills: the historical issue is not cured by inflating activity. **Do not rerun that same exact exhausted neighborhood as a candidate search without a new predeclared hypothesis or materially fresh independent data.**

PR #1815 (`81e81c887799bd9eea442ae6b5878925a5bd4287`) separately fixed fractional, quantized risk-overlay fill inflation in `bybit_strategy_search_v2.py`. Its completed real corrected-main run `36102660134`, artifact `10850490620` (`sha256:3fb9d940e05f012c32cf92d54885d4d90fd0623ac93a1e632d7b364b9f44979d`), evaluated 4,320 historical variants; 60 exact development evaluations passed but the selected historical breakout strategy failed both locked conservative and stress return/Sharpe/positive-ratio gates. Its explicit decision is `continue_research_no_promotion`, **not** a new untouched holdout or prospective candidate. The old v2 artifact `10840832732` reported 137 minimum development fills for a DIFFERENT selected strategy versus only 2 for the new selected strategy; old and corrected candidate reports must not be conflated.

The owner Lenovo desktop remains physically installed and independently proven as `NEXUS Personal Pro 5.1.0-77d23868` with three bounded retained versions. Code-only research and reporter merges do not by themselves require a new GUI install. Read-only `127.0.0.1:56108` APIs were rechecked after the above main changes: prospective Paper correctly displays `QUARANTINED`, 181 bars and both profiles at 3 fills; Live, orders, withdrawals, production promotion and credentials remain disabled. New candidate qualification is tracked in #1811: predeclare independent training-only research with explicit economic rationale, transaction-cost/turnover/activity discipline and an uninspected future holdout; require separate authentic prospective Paper and deterministic risk final review. No automatic promotion or Live/L4 authority.
