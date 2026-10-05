# NEXUS Master System Map

- Status: Proposed master operational map
- Version: `nexus-system-map/v1`
- Date: 2026-10-05
- Baseline main SHA: `a5e0d7fa7a2d9bc8baee5dff59a6518b078e09ea`
- Scope: Research + Demo/Paper only
- Supersedes: nothing. This document connects existing ADRs, workflows, runners, product surfaces and operational roles.
- Machine-readable registry: `config/nexus-system-map-v1.yaml`

## 1. Purpose

This is the top-level operational map for NEXUS. Every new change must be mapped to one or more node IDs below before implementation. Existing ADRs remain authoritative for their specific domains; this map exists to stop duplicated subsystems, conflicting runner roles, forgotten dependencies, and changes that bypass required gates.

GitHub is the source of truth for source code, reviewed configuration, workflow definitions, evidence contracts and release history. GitHub Actions is not the runtime database for the owner Paper terminal.

## 2. Non-negotiable invariants

1. Bybit remains the primary market/execution identity.
2. Demo/Paper only. `live_trading=false` everywhere in this map.
3. Reference Paper balance: 500 USDT.
4. A research result is evidence, not execution authority.
5. Training may select/rank candidates; validation/test/OOS must not select the winner.
6. No arbitrary minimum trade-count gate may be introduced as a hidden strategy selector.
7. Independent QA is required before qualification.
8. Qualification is required before a strategy can enter the Demo/Paper strategy matrix.
9. AI/LLM/agents may propose, research, explain and prepare bounded artifacts; they may not override deterministic risk or gain Live authority.
10. Laptop 1 is the single owner Runtime/Paper primary.
11. Laptop 2 is the Research/Build primary.
12. Failover runners are dormant until a watchdog proves the primary lane unhealthy.
13. Two Paper writers must never be active against the same owner state.
14. Existing healthy installs are preserved until a replacement has fixed-head verification and smoke evidence.
15. LBank/Bitget/Binance data may support research or reconciliation only under explicit provenance. They must not be silently relabeled as Bybit data.
16. Protective guard authority is reduce/close only. It must not open, reverse or enable Live execution.

## 3. Physical and logical topology

```text
                                      ┌──────────────────────────────────────┐
                                      │              GitHub                  │
                                      │ source truth / PR / ADR / CI / proof │
                                      └──────────────────┬───────────────────┘
                                                         │
                         ┌───────────────────────────────┼───────────────────────────────┐
                         │                               │                               │
                         v                               v                               v
              ┌───────────────────┐          ┌─────────────────────┐        ┌─────────────────────┐
              │ CONTROL PLANE     │          │ RESEARCH PLANE      │        │ BUILD / QA PLANE    │
              │ Mission Queue     │          │ Strategy Finder     │        │ tests / packaging   │
              │ Coordinator       │          │ Mechanism Factory   │        │ fixed-head evidence │
              │ Agent Manager     │          │ Generator           │        │ independent QA      │
              │ Orchestrator      │          │ AI Room             │        └──────────┬──────────┘
              └─────────┬─────────┘          └──────────┬──────────┘                   │
                        │                               │                              │
                        └───────────────────────────────┼──────────────────────────────┘
                                                        v
                                             ┌─────────────────────┐
                                             │ QUALIFICATION GATE  │
                                             │ fail closed         │
                                             └──────────┬──────────┘
                                                        │ qualified only
                                                        v
┌──────────────────────────────────────┐     ┌─────────────────────┐
│ LAPTOP 2 — DESKTOP-F4SA4VL          │     │ LAPTOP 1 — DESKTOP-1R1081M   │
│ ROLE: Research / Build Primary       │     │ ROLE: Runtime / Paper Primary │
│                                      │     │                               │
│ NEXUS-RESEARCH-RUNNER  ACTIVE        │     │ NEXUS-LOCAL-RUNNER   ACTIVE  │
│ NEXUS-LOCAL-FAILOVER    DORMANT      │     │ NEXUS-BYBIT-WSL      ACTIVE  │
│ NEXUS-BYBIT-FAILOVER    DORMANT      │     │ NEXUS-WINDOWS-DR     ACTIVE  │
│ NEXUS-RESEARCH-SECONDARY OFF         │     │ NEXUS-RESEARCH-FAILOVER STBY │
│ Paper writer: FORBIDDEN              │     │ Paper writer: SINGLE PRIMARY │
└──────────────────┬───────────────────┘     └──────────────┬────────────────┘
                   │                                        │
                   │ research evidence                      │ owner runtime
                   └──────────────────┬─────────────────────┘
                                      v
                         ┌──────────────────────────┐
                         │ DATA / MARKET PLANE      │
                         │ Bybit = primary identity │
                         │ Binance = corroboration  │
                         │ LBank = tertiary/research│
                         │ Bitget = auxiliary only  │
                         └────────────┬─────────────┘
                                      v
                         ┌──────────────────────────┐
                         │ PAPER PRODUCT RUNTIME    │
                         │ Decision -> Risk ->      │
                         │ Paper Execution ->       │
                         │ Event Store / Journal    │
                         │ Protective Exit          │
                         └────────────┬─────────────┘
                                      v
                         ┌──────────────────────────┐
                         │ PRODUCT SURFACES         │
                         │ Desktop / Dashboard      │
                         │ Market & Data            │
                         │ Research / Backtest      │
                         │ Demo / Positions         │
                         │ Mobile read visibility   │
                         └──────────────────────────┘
```

## 4. Node registry

### SYS-00 — Architecture / Governance

**Placement:** GitHub repository.

**Owns:** ADRs, authority matrices, versioned contracts, this master map, security boundaries, change-precheck rules.

**Primary references:** ADR-005, Phase 4 Authority Matrix, ADR-009, ADR-023, module contract registry.

**Rule:** no implementation change may contradict an accepted ADR without an explicit ADR update.

---

### CTRL-10 — Mission Control / Mission Queue

**Placement:** GitHub control plane; runtime code includes `mission_control.py`, `mission_runner.py`, mission queue workflows.

**Inputs:** approved task definitions, exact source SHA, policy, dependency state.

**Outputs:** bounded mission lease/status/evidence.

**Authority:** orchestration only. No trading authority.

**Anti-duplication rule:** a mission must have one active lease/owner; failover may take over only after the prior lease is dead/expired/fenced.

---

### CTRL-11 — Agent Manager / Coordinator

**Placement:** GitHub control plane and bounded worker processes.

**Components:** `agent_manager.py`, `agent_manager_runner.py`, `fast_agent_orchestrator.py`, `nexus_autonomous_orchestrator.py`, coordinator workflows.

**Owns:** task routing, capability assignment, retry/fencing, dispatch sequencing.

**Does not own:** strategy qualification, risk approval, Paper accounting.

**Required inputs:** exact main SHA, current System Map node, mission dependency state, source-exact evidence.

---

### CTRL-12 — AI Control Plane / AI Room

**Placement:** application/control layer; research-oriented.

**Components:** `ai_control_plane.py`, `ai_room.py`, `nexus_ai_room_boundary.py`, DeepSeek provider/egress modules.

**Authority:** propose, analyze, summarize, generate bounded research artifacts.

**Forbidden:** direct Paper state mutation, deterministic risk override, credentials, Live execution.

---

### DATA-20 — Source Adapters

**Primary identity:** Bybit.

**Secondary corroboration:** Binance where canonical mapping proves compatibility.

**Tertiary:** LBank, explicit research-only provenance.

**Auxiliary:** Bitget public/demo collector may be used for research comparison, but has no higher authority than ADR-009 and must never be silently substituted for Bybit.

**Components include:** Bybit public/archive collectors, LBank collectors, Bitget public collector, reconciliation modules.

**Output:** source-labelled immutable/canonical datasets plus provenance.

---

### DATA-21 — Provenance / Integrity / Readiness

**Placement:** shared deterministic data layer + CI evidence.

**Components:** `market_data_provenance_manifest.py`, `market_data_source_validator.py`, `data_readiness.py`, candle/inventory/gap audits, cross-source reconciliation.

**Gate:** malformed, stale, substituted, unresolved-gap, checksum-mismatch or ambiguous data fails closed.

**Consumers:** Research, Backtest, Strategy Finder, Paper runtime. Consumers must not bypass readiness.

---

### RES-30 — Strategy Finder

**Placement:** Laptop 2 is physical research primary; GitHub-hosted workflows may prepare/cache/verify research inputs.

**Purpose:** discover materially new strategy mechanisms, not recycle indicator-only templates.

**Inputs:** DATA-21 qualified data, mechanism catalog/frontier, research memory, bounded AI proposals.

**Outputs:** immutable research candidates with provenance and topology/config fingerprints.

**Selection rule:** Training only may rank/select.

---

### RES-31 — Mechanism Factory / Generator

**Placement:** Research plane, primarily Laptop 2 for owner compute; CI verifies contracts.

**Components:** `nexus_mechanism_factory.py`, composite research, generator/frontier mechanisms.

**Rule:** declarative/whitelisted primitives only; no `eval`, `exec`, arbitrary downloaded code or self-authorizing strategy code.

**Novelty:** new candidate must prove material distinction from the evaluated frontier.

---

### RES-32 — Backtest / Multi-pair / Multi-timeframe

**Placement:** Research plane.

**Components:** canonical backtest engine, multi-timeframe discovery, multi-pair discovery, monthly backtest reports.

**Required outputs per strategy:** pair, timeframe, date window, trade count, aggregate P/L, mean trade result, costs/slippage assumptions, drawdown, regime breakdown where applicable.

**Rule:** low trade count is evidence, not an automatic rejection by an arbitrary minimum.

---

### VAL-40 — Validation / OOS / Stress

**Placement:** deterministic validation lane; may run hosted or on the research runner depending on workflow contract.

**Purpose:** estimate generalization, not choose the Training winner.

**Includes:** conservative/stress costs, cross-pair validation, walk-forward/OOS, leakage tests, invariance tests.

**Failure:** candidate remains Research/Rejected; no Demo mutation.

---

### QA-41 — Independent QA

**Placement:** independent worker/lane from the producer whenever possible.

**Logical role:** `qa-verifier-agent`.

**Inputs:** immutable producer evidence and exact source SHA.

**Checks:** digest/provenance, reproducibility, leakage, authority fields, training-vs-validation separation, Live=false.

**Output:** QA attestation or rejection.

**Rule:** the producing research agent cannot self-approve.

---

### QUAL-42 — Qualification Gate

**Placement:** deterministic control layer after VAL-40 + QA-41.

**Inputs:** research package, validation evidence, QA attestation, policy/registry.

**Output:** `qualified=true/false` with reason codes.

**Authority:** permits entry into Demo/Paper candidate registry only. It never grants Live authority.

---

### REG-50 — Strategy / Config Registries

**Placement:** reviewed versioned repository config + approved runtime copy.

**Owns:** strategy identity/version, qualified status, Demo matrix membership, regime policy, source policy.

**Rule:** no UI or agent may silently mutate registry authority.

---

### RUNTIME-60 — Decision Engine

**Placement:** Laptop 1 owner runtime.

**Inputs:** qualified strategy signals, regime context, portfolio context, policy versions.

**Output:** structured proposal only.

**Cannot:** bypass Risk Engine.

---

### RISK-61 — Deterministic Risk Engine

**Placement:** Laptop 1 owner runtime.

**Authority:** final eligibility gate for every Paper state transition.

**Checks:** exposure, concentration, stale/duplicate signal, drawdown, policy, kill switch, ordering, malformed inputs.

**AI override:** forbidden.

---

### PAPER-62 — Paper Execution

**Placement:** Laptop 1 only as owner writer.

**Mode:** Demo/Paper; reference balance 500 USDT.

**Identity:** Bybit semantics.

**Owns:** deterministic simulated fills, fees, slippage, stop/target, reduce/close/rebalance transitions.

**Single-writer invariant:** Laptop 2 must not run the owner Paper writer.

---

### PAPER-63 — Event Store / Portfolio / ProductRuntime Journal

**Placement:** owner runtime data on Laptop 1, with backup/export evidence where designed.

**Components:** `nexus_event_store.py`, isolated Paper ledger/runtime, ProductRuntime journal integration.

**Storage rule:** append/replay under schema and integrity rules. GitHub is not the owner runtime database.

**Recovery:** previous-valid state wins over invalid replay candidates.

---

### SAFE-64 — Protective Exit Guard

**Placement:** Laptop 1.

**Authority:** reduce/close only.

**Inputs:** closed market candles + existing Paper positions + stop/target rules.

**Forbidden:** open new positions, reverse exposure, increase exposure, Live action.

**Process rule:** one effective guard instance. Duplicate launchers must be consolidated behind a mutex/watchdog rather than allowed to create parallel execution.

---

### UI-70 — Desktop Product

**Placement:** Laptop 1 primary product installation.

**Surfaces:** Data & Market, AI Room, Strategy Finder/Research, Backtest evidence, Demo/Paper positions/history, diagnostics.

**Rule:** UI displays approved/runtime state; it does not directly mutate protected accounting/risk state.

---

### UI-71 — Mobile / Remote Visibility

**Placement:** mobile client + read gateway on owner environment.

**Components:** Android surface, `mobile_paper_gateway.py`, secure gateway contracts.

**Primary purpose:** observe owner Demo positions/history/PNL/SL/TP and approved status.

**Mutation:** only through validated command paths if separately authorized; never direct event-store writes.

---

### OBS-80 — Observability / Failure Triage

**Placement:** GitHub workflows + local watchdogs.

**Includes:** event-driven failure triage, source-health checks, runner diagnostics, evidence refresh, health reports.

**Rule:** monitoring may detect and trigger bounded recovery but cannot weaken gates to restore availability.

---

### REL-90 — Build / Release / Install

**Placement:** GitHub build/verification + Laptop 2 for build/research support + Laptop 1 for staged product verification.

**Flow:** exact-main source -> tests -> reproducible package -> staging -> smoke -> cutover.

**Rule:** healthy Laptop 1 install remains intact until replacement package is verified.

## 5. Runner placement and responsibility

| Runner / lane | Physical placement | Normal state | Primary responsibility | Must not do |
|---|---|---|---|---|
| `NEXUS-LOCAL-RUNNER` | Laptop 1 | ACTIVE | owner local/runtime jobs | duplicate Research primary; Live |
| `NEXUS-BYBIT-WSL` | Laptop 1 | ACTIVE | Bybit-network-specific owner jobs | become second Paper writer elsewhere |
| `NEXUS-WINDOWS-DR` | Laptop 1 | ACTIVE | Windows DR/readiness/recovery jobs | bypass fixed-head/release gates |
| `NEXUS-RESEARCH-RUNNER` | Laptop 2 | ACTIVE | Strategy Finder, research/backtest compute | owner Paper writer |
| `NEXUS-RESEARCH-FAILOVER` | Laptop 1 | STANDBY | research only after Laptop 2 health failure | run continuously beside research primary |
| `NEXUS-LOCAL-FAILOVER` | Laptop 2 | DORMANT | local runner takeover after proven Laptop 1 failure | always-on duplicate |
| `NEXUS-BYBIT-FAILOVER` | Laptop 2 | DORMANT | Bybit lane takeover after proven primary failure | always-on duplicate |
| `NEXUS-RESEARCH-SECONDARY` | Laptop 2 | OFF | retired/secondary registration only | active parallel research unless explicitly reassigned |
| GitHub-hosted Ubuntu lanes | GitHub | ON DEMAND | CI, deterministic tests, artifacts, lightweight research preparation | owner runtime DB; Live |
| `nexus-bybit-network` workflow lane | routed by workflow/labels | ON DEMAND | physical/network-qualified Paper/Bybit workflow steps | silently substitute another source |

## 6. Laptop role contract

### Laptop 1 — `DESKTOP-1R1081M`

Role: **Runtime/Paper Primary**

Owns:
- single owner Paper writer;
- ProductRuntime journal/event state;
- Bybit/local owner runtime lanes;
- Desktop product;
- Protective Exit;
- Windows DR;
- research failover only when Laptop 2 is proven unhealthy.

Expected machine role:
```json
{
  "role": "runtime_paper_primary",
  "paper_writer": true,
  "research_failover": "watchdog_only",
  "local_runner_primary": true,
  "bybit_runner_primary": true,
  "live_trading": false
}
```

### Laptop 2 — `DESKTOP-F4SA4VL`

Role: **Research/Build Primary + Conditional Runtime Failover**

Owns:
- research runner;
- Strategy Finder / backtest compute;
- build/support jobs where useful;
- Local/Bybit failover only after watchdog proof.

Must not own:
- active owner Paper writer.

Expected machine role:
```json
{
  "role": "research_primary_conditional_failover",
  "research_runner": "NEXUS-RESEARCH-RUNNER",
  "paper_writer": false,
  "local_failover": "watchdog_only",
  "bybit_failover": "watchdog_only",
  "live_trading": false
}
```

## 7. Workload routing

| Work type | Primary executor | Secondary/failover | Source of truth |
|---|---|---|---|
| Pull requests / reviews / architecture | GitHub | none | GitHub |
| Fast unit/contract tests | GitHub-hosted | local if workflow requires | GitHub |
| Strategy discovery | Laptop 2 Research runner | Laptop 1 Research failover | GitHub mission/evidence |
| Heavy backtest | Laptop 2 Research runner | Laptop 1 failover | immutable dataset + GitHub config |
| Independent QA | separate QA lane | hosted/local as contract permits | immutable evidence |
| Data reconciliation | hosted/research lane | bounded fallback | provenance registry |
| Owner Paper runtime | Laptop 1 | explicitly fenced failover only | owner event store + GitHub policy |
| Protective exits | Laptop 1 | recovery path only | owner Paper state |
| Windows package smoke | Laptop 1 staged install | Laptop 2 build support | exact main SHA |
| Mobile build | GitHub/build lane | Laptop 2 build support | exact main SHA |
| Remote recovery | each laptop's watchdog | other laptop for service continuity | role registry |

## 8. End-to-end research-to-Paper flow

```text
External public sources
        |
        v
DATA-20 Source Adapters
        |
        v
DATA-21 Provenance / Readiness
        |
        v
RES-30 Strategy Finder
        |
        +--> RES-31 Mechanism Factory / Generator
        |
        v
RES-32 Training Backtest / ranking
        |
        v
VAL-40 Locked validation / OOS / stress
        |
        v
QA-41 Independent QA
        |
        v
QUAL-42 Qualification
   |             |
 false           true
   |             |
 research        v
 archive      REG-50 Demo strategy registry
                 |
                 v
            RUNTIME-60 Decision
                 |
                 v
            RISK-61 Deterministic risk
                 |
                 v
            PAPER-62 Paper execution
                 |
                 +--> SAFE-64 Protective Exit
                 |
                 v
            PAPER-63 Event Store / Journal
                 |
                 v
            UI-70 / UI-71
```

No arrow may skip DATA-21, QA-41, QUAL-42 or RISK-61.

## 9. Failover model

Failover is **conditional**, not load sharing.

### Research failure
1. `NEXUS-RESEARCH-RUNNER` on Laptop 2 becomes unhealthy.
2. L1 watchdog confirms repeated failure.
3. `NEXUS-RESEARCH-FAILOVER` may start bounded research work.
4. When L2 is healthy for the required consecutive checks, L1 research failover stops.
5. Mission fencing prevents both from committing the same logical result.

### Local/Bybit runtime failure
1. L1 primary runner health becomes unhealthy.
2. L2 watchdog confirms repeated failure.
3. Corresponding failover runner starts only the allowed bounded lane.
4. Paper single-writer ownership must be explicitly fenced before any writer takeover.
5. Recovery does not relax Live=false, provenance, risk or source rules.

## 10. GitHub workflow placement

Workflows are grouped by responsibility, not treated as separate products:

- **Control:** mission queue, coordinator, autopilot policy, event-driven failure triage.
- **Research:** multi-timeframe discovery, multipair discovery, mechanism research, research evidence refresh.
- **Data:** Bybit archive/backfill/audit, LBank collection, source health, reconciliation.
- **Paper:** persistent Paper loop, regime lifecycle, Paper boundary/requalification.
- **Runner health:** Local runner, Bybit WSL diagnostics/wake, Windows DR/bootstrap, transport probes.
- **Build/release:** Windows desktop build, Android build, build verification, release readiness/recovery.
- **Proof:** reproducibility, final evidence, physical proof/restart replay.

A new workflow must attach to one of these groups and one System Map node. A new workflow that duplicates an existing group's responsibility requires an explicit deprecation/migration plan.

## 11. Product surface map

### Data & Market
Reads DATA-20/DATA-21 state and source provenance. Shows source identity and freshness. It must make fallback provenance visible.

### Strategy Finder / Research
Reads RES-30/31/32 and VAL-40 evidence. Shows candidate mechanism, pair/timeframe, backtest window, trade count, P/L, averages, validation/stress and rejection reasons.

### AI Room
Front-end for CTRL-12 advisory/research actions. It cannot directly promote or execute.

### Demo/Paper
Reads PAPER-63 owner state. Shows open positions, PNL, entry, size, SL, TP, timestamps, strategy/timeframe, history and protective-exit state.

### Mobile
Primarily reads the same approved owner Paper state through the secure gateway. It must not create a second accounting truth.

## 12. Roadmap layers

### R0 — Governance and topology
Master map, ADRs, authority, machine role registry, change precheck.

### R1 — Runner and resilience stabilization
Single-role runners, watchdog-only failover, restart recovery, duplicate-process elimination.

### R2 — Market Data
Bybit primary, explicit backup research feeds, provenance/readiness, market UI.

### R3 — Strategy Research
Strategy Finder, modern mechanism discovery, AI Room research support, novelty frontier.

### R4 — Backtest / Validation
Multi-pair, multi-timeframe, monthly tables, cost/stress/OOS, leakage controls.

### R5 — Independent QA / Qualification
Separate verifier, immutable evidence, deterministic qualification.

### R6 — Demo/Paper Product Runtime
500 USDT owner state, multi-strategy runtime, full position lifecycle, protective exits, ProductRuntime journal.

### R7 — Product UX
Professional Desktop sections, Research evidence, Data & Market, Demo history, mobile visibility.

### R8 — Operational hardening
Reproducible releases, DR, recovery drills, observability, stale-PR cleanup, supportable handoff.

Live trading is not a roadmap layer.

## 13. Mandatory change precheck

Before any implementation, record:

```text
Change:
System Map node(s):
Existing component being changed:
Why existing component cannot already satisfy the need:
Primary runner / execution lane:
Data source and provenance:
Upstream dependencies:
Downstream consumers:
Authority level:
Paper/Live boundary:
Duplicate-work check:
Failure mode:
Rollback:
Tests:
Independent QA required:
Deployment/cutover impact:
Evidence required to declare DONE:
```

A change is blocked if its node, owner, dependency direction or authority cannot be identified.

## 14. Definition of DONE

A node/change is DONE only when:
- code/config is merged at a known SHA;
- relevant tests are green on the exact head;
- architecture/contracts are still valid;
- runtime placement matches this map;
- duplicate runners/processes are not introduced;
- provenance and failure behavior are verified;
- rollback/recovery is known;
- no Live authority was introduced;
- user-visible behavior is verified when applicable.

“Implemented” without this evidence is not “DONE”.

## 15. Current operational checkpoint

At the baseline for this map:
- Laptop 1 is designated Runtime/Paper primary.
- Laptop 2 is designated Research primary.
- Local/Bybit failover on Laptop 2 is watchdog-only, not continuously active.
- Research failover on Laptop 1 is standby.
- `NEXUS-RESEARCH-SECONDARY` is not part of normal active topology.
- GitHub remains source of truth.
- Live trading remains disabled.

This checkpoint describes intended/current operational roles. Runner health is dynamic and must be re-verified before actions that depend on current online state.
