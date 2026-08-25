# NEXUS Project Map

This document is the navigation layer for the current NEXUS repository. It does not replace code, tests, ADRs, evidence, or GitHub acceptance issues. Its purpose is to stop the project from becoming a collection of disconnected historical phases, experiments, branches, workflows, and product surfaces.

## Source-of-truth order

When two project descriptions disagree, use this order:

1. **Current `main` code, tests, and protected workflows** — executable behavior outranks old prose.
2. **Durable Project Memory state** — `docs/project_memory/STATE.json` records completed phases and fixed evidence identifiers.
3. **Architecture ADRs and machine-readable contracts** under `docs/architecture/`.
4. **Replayable evidence** under `docs/evidence/`, workflow artifacts, and issue evidence markers.
5. **Closed Phase 7 acceptance issues** — parent `#696`, lanes `#697`–`#700`, inventory `#701`, proof mission `#702`, and product acceptance `#692` remain historical acceptance evidence.
6. **Historical phase documents and legacy research notes** — useful context, but not current acceptance authority.

A closed historical phase is not silently reopened. If current evidence proves a prior capability false-green, the affected dependency must be explicitly reclassified.

## Phase status

| Phase | Repository parent | Status | Meaning |
|---|---:|---|---|
| Phase 3 | `#389` | CLOSED / completed | Historical prerequisite |
| Phase 4 | `#510` | CLOSED / completed | Historical prerequisite |
| Phase 5 | `#583` | CLOSED / completed | Durable contracts/state/verification foundation |
| Phase 6 | `#591` | CLOSED / completed | Canonical research integration foundation |
| Phase 7 | `#696` | **CLOSED / completed** | Fixed-SHA integration and physical proof acceptance complete |

The current authority boundary remains **Research / Backtest / Paper only**. No Live/L4 authority is implied by Phase 7 completion. Bybit remains the primary canonical market reference; Binance is secondary corroboration and LBank is tertiary/legacy research only.

## Current final-proof acceptance

`nexus_final_proof_mission.py` is the fail-closed acceptance verifier for the
current integration chain. It binds Supervisor, resource-utilization,
Mission-Control, and Project-Memory projections to one fixed Git SHA. It does
not convert registration or heartbeat into execution: every `EXECUTED`
resource requires task, lease, result, evidence, and verifier digests.
DeepSeek must be reported as `EXECUTED` or `UNAVAILABLE` truthfully; no provider
claim is inferred. The Windows laptop may be reported truthfully as `EXECUTED`,
`UNAVAILABLE`, or `BLOCKED`, but final acceptance requires `EXECUTED` with
canonical task/lease/result/evidence/verifier digests. A successful validator
result remains Paper-only and keeps
`live_trading_authority=false`.

`nexus_final_proof_assembler.py` is the data-only convergence point. It reads
already-produced Supervisor, Mission-Control, scheduler, resource-utilization,
and canonical Project-Memory evidence, rejects cross-SHA substitution, and only
then invokes the independent final verifier. It does not execute or fabricate a
missing Windows workload.

## Phase 7 lanes

### Lane A — AI Control Plane / Resource Manager (`#697`)

Required path:

`Mission -> Supervisor -> Router/Resource Manager -> Worker -> heartbeat/result -> Evidence -> Independent Verifier -> next task`

Primary existing implementation surfaces:

- `agent_manager.py`
- `agent_manager_runner.py`
- `agent_transport.py`
- `ai_control_plane.py`
- `.github/workflows/`
- Windows local-runner/bootstrap scripts under `scripts/`
- packaged Windows bootstrap under `desktop/nexus-product/`

Current acceptance emphasis:

- real task allocation, not status-only telemetry;
- deterministic routing reasons;
- leases/fencing and authenticated result binding;
- zero-idle behavior for independent READY tasks;
- truthful EXECUTED/UNAVAILABLE resource ledger;
- physical Windows runner proof where the laptop is actually used.

### Lane B — Data Intelligence / Regime Engine (`#698`)

Canonical path:

`Validated Data -> Features -> Market Structure -> Volatility/Liquidity -> Regime -> Cross-timeframe Context -> Strategy Features`

Existing foundations include:

- `bybit_public_klines.py`
- `market_data_provenance_manifest.py`
- `phase5_data_binding.py`
- `data_readiness.py`
- `research_data.py`
- source contracts under `docs/architecture/`

Phase 7 acceptance requires deterministic/versioned feature and regime evidence, provenance binding, no look-ahead, replayability, and typed outputs consumable downstream.

### Lane C — Strategy Factory (`#699`)

Canonical lifecycle:

`IDEA -> RESEARCHED -> BACKTESTED -> VALIDATED -> CANDIDATE -> PAPER -> QUARANTINED/REJECTED`

Existing foundations include:

- `backtest_engine.py`
- `phase5_strategy_factory.py`
- `phase6_research_pipeline.py`

Every immutable strategy version must bind hypothesis, parameters, data revision/provenance, code SHA, IS/OOS windows, execution-cost assumptions, regime evidence, metrics, kill criteria, evidence digests, and lifecycle state.

Promotion/demotion remains deterministic and evidence-gated; AI may advise but may not promote a strategy by discretion.

### Lane D — Realistic Paper Execution (`#700`)

Canonical path:

`Signal/Decision -> Deterministic Risk -> Order Intent -> Simulated Exchange -> Fill/Partial Fill -> Fees/Slippage/Latency -> Reconciliation -> PnL -> Audit`

Architecture foundation includes `docs/architecture/ADR-010-paper-event-store.md` and the existing deterministic Risk/Paper contracts already present in the repository.

Phase 7 acceptance requires replayable Paper state, Backtest/Paper parity at Strategy/Decision/Risk boundaries, realistic bounded execution differences, reconciliation, kill switches, and Paper-only futures mechanics where applicable.

## Cross-lane convergence

The Phase 7 exit path is `#702`:

`Mission -> Supervisor -> Router -> Workers -> Evidence -> Independent Verifier -> Canonical Data -> Data Intelligence/Regime -> Strategy Factory -> Decision -> Deterministic Risk -> Paper -> Performance/Drift -> Mission Control`

`#702` is not documentation-only. At least one fixed final SHA must produce replayable end-to-end evidence.

Mission Control acceptance remains tracked by `#692`. The Windows/Android product must expose the same real durable task/resource/strategy/paper/evidence state; static cards, fabricated workers, and GitHub-only status do not satisfy acceptance.

## Verified Phase 7 execution order

1. Prove the corrected Windows runner/autostart path on the physical owner laptop.
2. Complete the applicable local-laptop slice of `#702` with real returned evidence.
3. Prove Lane A resource allocation, routing reasons, zero-idle scheduling, and verifier separation.
4. Feed canonical validated data into Lane B and produce deterministic regime/features evidence.
5. Drive at least one strategy family through Lane C to deterministic Candidate or Reject.
6. Pass the accepted output through Decision -> deterministic Risk -> Lane D Paper execution/reconciliation.
7. Produce Performance/Drift evidence.
8. Project exactly the same state into Mission Control (`#692`).
9. Run the complete fixed-SHA Phase 7 proof and close only gates with replayable acceptance evidence.

These steps are retained as the completed acceptance trace, not as an open work queue. Current maintenance must preserve their evidence and fail closed if a regression invalidates a dependency. A new phase, production release, Live/L4 path, credential use, signing, or billing authority requires a separate explicit owner-approved contract.

## Repository organization policy

The repository contains significant historical material. Cleanup must therefore be incremental rather than a mass move.

### Keep stable for now

- imported Python module paths;
- protected workflow paths/names;
- evidence paths referenced by acceptance issues;
- historical ADR filenames, even where numbering is duplicated;
- phase-specific filenames that are still imported or cited.

### New organization rule

New work should be classified before implementation as one of:

- `control-plane`
- `data-intelligence`
- `strategy-factory`
- `paper-execution`
- `mission-control`
- `evidence/verification`
- `infrastructure` (only when blocking an active lane)

Every new PR should name the completed Phase 7 lane it preserves, identify a bounded defect/maintenance contract, or reference a separately approved future phase.

### ADR cleanup rule

Existing duplicate ADR identifiers are treated as historical immutable filenames to avoid breaking references. Do not create another duplicate identifier. A later dedicated cleanup may add an ADR index and aliases without rewriting history.

### Branch cleanup rule

The repository has many historical `agent/*` and `nexus/*` branches. They must not be bulk-deleted blindly. Branch cleanup should classify each branch as:

- ACTIVE — backs an open PR/current proof;
- MERGED-REFERENCE — merged historical reference, safe to prune after verification;
- STALE/ABANDONED — no open PR and no unique required commit/evidence;
- PROTECTED/HANDOFF — retained intentionally for recovery/evidence.

Delete only after the classification is evidence-backed.

## Definition of organized

NEXUS is considered structurally organized when a maintainer can answer these questions without reconstructing project history from dozens of PRs:

1. Which Phase/Lane owns this component?
2. What is its canonical contract?
3. What code implements it?
4. What test/evidence proves it?
5. What downstream component consumes it?
6. Does this change preserve the completed Phase 7 acceptance evidence and authority boundary?

This map is the starting index; executable code and acceptance evidence remain authoritative.

## Machine-readable integration graph

The canonical component connection matrix is maintained in
`config/nexus-integration-registry.json` and fail-closed validated by
`nexus_integration_validator.py`. Each connection records its producer, consumer,
versioned contract, durable-state surface, independent verifier, evidence, and current
verification classification. Missing canonical edges, missing repository evidence,
self-verification, AI authority expansion, Paper authority expansion, and any Live
Trading activation are rejected.

This registry does not replace the fixed-SHA Phase 7 proof. It prevents later
maintenance from silently leaving a component present but disconnected from its real
consumer or verification path.

Every autonomous dispatch is additionally fail-closed against
`config/nexus-execution-contract.json`. `nexus_autonomous_orchestrator.py` requires a
complete per-task execution record and a satisfied pre-execution checklist before it
selects work; allowlisting alone is not sufficient proof of usable work.

The AI Room boundary is independently checked by `nexus_ai_room_boundary.py`: the
room may observe, review, propose, and route through its two bounded reversible tools,
but it cannot import or directly invoke Strategy lifecycle, deterministic Risk, Paper
execution/event-store, or worker-management mutation authority.

## Verified maintenance execution cycle

`nexus_verified_execution_cycle.py` composes the existing Mission, task-attempt,
lease/fencing, result-ingestion, evidence, and independent-verification contracts into
one bounded replayable maintenance cycle. Its built-in workload validates the merged
integration registry and writes an atomic resource-utilization ledger only after the
producer result is accepted for the current fence and a verifier in a different trust
domain passes every check. A heartbeat, registration, failed workload, stale/spoofed
result, self-verification, or Live/L4 authority can never produce `VERIFIED`.

## Persistent Strategy/Paper Supervisor cycle

`nexus_strategy_paper_supervisor.py` is the repository-owned operational bridge from
the verified execution contract into the existing Strategy and Paper components. One
bounded run fetches a canonical public Bybit dataset, creates a separately fenced task
for each approved strategy family, runs deterministic qualification, and routes only a
valid Candidate through Decision, deterministic Risk, and an isolated Paper portfolio.

Each family persists its own evidence and portfolio state under `NEXUS_STATE_DIR`.
The final Supervisor ledger is accepted only by a separate contract verifier and records
actual task/lease/result/evidence use. A killed strategy is a valid verified research
outcome; it is never promoted to Paper. The cycle has no Live/L4, private exchange,
credential, signing, billing, or deployment authority.

## Paper performance, drift, and quarantine bridge

`nexus_paper_performance_drift.py` binds closed Paper trades to the exact task inside
an independently re-verified Supervisor ledger. A detached task, mutated ledger,
rejected qualification, missing Paper evidence, family/data mismatch, or Live authority
fails closed. A newly accepted Paper execution receives a replayable `CANDIDATE -> PAPER`
lifecycle transition before performance health is evaluated.

The bridge reuses the canonical `performance_analytics.py`, `strategy_registry.py`, and
`strategy_lifecycle.py` contracts. It emits deterministic expectancy, fee, drawdown and
regime evidence; insufficient samples remain explicitly `INSUFFICIENT_EVIDENCE`; severe
drift appends `QUARANTINED`. It has no promotion, exchange, signing, credential, or Live
Trading authority.

## Frozen Bybit strategy prospective Paper forward

`bybit_prospective_paper_forward_v1.py` advances the qualified frozen
`bybit_btc_eth_regime_consensus_v1` strategy through a separate prospective
Paper evidence lane. Its start cutoff is `2026-08-26T00:00:00Z`; earlier bars
cannot enter the chain. A scheduled, non-overlapping workflow resumes the latest
digest-protected state every four hours and uses only public Bybit Spot and linear
perpetual data.

The strategy manifest and parameters are SHA-256 bound. Conservative and stress
Paper accounts remain separate while actual funding, public instrument/risk-tier
metadata, execution-window liquidity, fees, margin and liquidation are recorded.
Thirty elapsed days and 180 completed 4-hour bars are required before a decision.
Passing can produce only `COMPLETE_REVIEW_REQUIRED`; failing is quarantined. The
lane accepts no private credentials, places no exchange orders, and has no Live/L4
or automatic-promotion authority.

## Closed Paper trades to Mission Control

`nexus_paper_performance_pipeline.py` completes the read path from the append-only Paper
journal to Mission Control. It independently validates and replays each hash-chained
journal, reconstructs only fully closed positions, binds fee and slippage records by
correlation ID, and feeds the resulting closed trades into the verified drift monitor.
Partial reductions and reversals fail closed until a separate deterministic attribution
contract exists; they are never guessed or silently flattened.

The multi-strategy projection is bound to an independently verified Supervisor ledger
and exposes family, strategy ID, lifecycle, sample count, expectancy, net PnL, drawdown,
and health status. Its durable JSON commit is atomic and digest-protected. The projection
is explicitly Paper-only, grants no promotion authority, and keeps Live Trading disabled.
