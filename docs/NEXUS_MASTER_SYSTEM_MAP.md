# NEXUS Master System Map

**Status:** Active operational architecture  
**Scope:** Research / Backtest / Demo-Paper only  
**Live Trading:** **OFF**  
**Paper reference balance:** 500 USDT  
**Current baseline main:** `a5e0d7fa7a2d9bc8baee5dff59a6518b078e09ea`

This map is the operational navigation layer for NEXUS. It complements
`config/nexus-integration-registry.json` (logical component contracts) and
`config/nexus-deployment-topology.json` (physical placement and runner routing).

## 1. System-wide topology

```text
OWNER
  |
  v
PROJECT MEMORY
  |
  v
AI ROOM / COUNCIL -----------------------------+
  | proposal only                              |
  v                                            |
MISSION                                        |
  |                                            |
  v                                            |
SUPERVISOR / COORDINATOR                       |
  |                                            |
  +--> ROUTER / AGENT MANAGER                  |
  |       |                                    |
  |       +--> Research Agent -----------------+----> EVIDENCE
  |       +--> QA Verifier -------------------------^   |
  |       +--> Cloud / DeepSeek worker                 |
  |                                                     v
  |                                             INDEPENDENT QA
  |                                                     |
  +-----------------------------------------------------+
                                                        |
                                                        v
MARKET DATA --> CANONICAL DATA --> DATA INTELLIGENCE --> STRATEGY FINDER
   |                                                    |
   |                                                    v
   |                                            MECHANISM FACTORY
   |                                                    |
   |                                            GENERATOR v1/v2/v3
   |                                                    |
   |                                                    v
   +----------------------------------------------> BACKTEST
                                                        |
                                                        v
                                                VALIDATION / STRESS
                                                        |
                                                        v
                                                QUALIFICATION GATE
                                                   /          \
                                             REJECT          CANDIDATE
                                                |               |
                                                +--> RESEARCH   v
                                                           DECISION
                                                              |
                                                              v
                                                    DETERMINISTIC RISK
                                                              |
                                                              v
                                                   PAPER EVENT STORE
                                                              |
                                                              v
                                                 PAPER EXCHANGE SIM
                                                              |
                                        +---------------------+------------------+
                                        |                                        |
                                  PROTECTIVE EXIT                         PAPER JOURNAL
                                        |                                        |
                                        +---------------------+------------------+
                                                              |
                                                              v
                                                     PERFORMANCE / DRIFT
                                                              |
                                                              v
                                                       MISSION CONTROL
                                                              |
                                     +------------------------+------------------+
                                     |                        |                  |
                                 DESKTOP UI                WEB API          MOBILE VIEW
```

No AI component can bypass Qualification, deterministic Risk, independent QA, or the
Paper-only boundary.

## 2. Physical deployment map

```text
                         GitHub / Cloud
                +-------------------------------+
                | PR / CI / Build Verification  |
                | Coordinator / Workflow state  |
                | Artifact transport            |
                | Independent cloud checks       |
                +---------------+---------------+
                                |
                   source/evidence only
                                |
              +-----------------+------------------+
              |                                    |
              v                                    v
+-----------------------------+      +-----------------------------+
| LAPTOP 1                    |      | LAPTOP 2                    |
| DESKTOP-1R1081M             |      | DESKTOP-F4SA4VL             |
| ROLE: RUNTIME/PAPER PRIMARY |      | ROLE: RESEARCH PRIMARY      |
|                             |      |                             |
| NEXUS-LOCAL-RUNNER          |      | NEXUS-RESEARCH-RUNNER       |
|   primary Windows runtime   |      |   primary research/backtest |
|                             |      |                             |
| NEXUS-BYBIT-WSL             |      | NEXUS-LOCAL-FAILOVER        |
|   primary Bybit network     |<-----|   standby only              |
|                             |      |                             |
| NEXUS-WINDOWS-DR            |      | NEXUS-BYBIT-FAILOVER        |
|   rescue / DR only          |<-----|   standby only              |
|                             |      |                             |
| Desktop NEXUS               |      | NEXUS-RESEARCH-SECONDARY    |
| Paper writer                |      |   disabled standby          |
| Protective Exit             |      |                             |
| Paper journal / product     |      | NO PRIMARY PAPER WRITER     |
| state                       |      |                             |
|                             |      |                             |
| Research failover watchdog |----->| Research primary health     |
+-----------------------------+      +-----------------------------+
```

### Machine role rule

**Laptop 1 owns runtime state.** It is the normal home of the desktop application,
500-USDT Paper account, Paper writer, protective-exit loop, local integration runner,
Bybit-network runner and Windows DR capability.

**Laptop 2 owns research compute.** It is the normal home of Strategy Finder,
mechanism research, backtests and the canonical research runner. Its Local and Bybit
runners are conditional failovers only. It must not become a second Paper writer.

## 3. Runner placement and authority

| Runner | Physical host | Mode | Normal workloads | Must NOT do |
|---|---|---|---|---|
| `NEXUS-LOCAL-RUNNER` | Laptop 1 | **PRIMARY** | physical Windows integration, owner-runtime checks | Research duplication, Live |
| `NEXUS-WINDOWS-DR` | Laptop 1 | **RECOVERY** | remote rescue, disaster recovery | general-purpose parallel work |
| `NEXUS-BYBIT-WSL` | Laptop 1 / WSL | **PRIMARY** | Bybit public-network/data workloads | Live/private-order authority |
| `NEXUS-RESEARCH-RUNNER` | Laptop 2 | **PRIMARY** | Strategy Finder, backtests, mechanism research | Paper writer, Live |
| `NEXUS-RESEARCH-SECONDARY` | Laptop 2 | **DISABLED STANDBY** | research failover only | run beside healthy Research primary |
| `NEXUS-LOCAL-FAILOVER` | Laptop 2 | **CONDITIONAL STANDBY** | local Windows failover | always-on duplicate local runner |
| `NEXUS-BYBIT-FAILOVER` | Laptop 2 / WSL | **CONDITIONAL STANDBY** | Bybit-network failover | always-on duplicate Bybit runner |

Observed baseline after role cleanup: primary Local, Bybit, Research and Windows-DR
runners are online; the three duplicate/failover runners are intentionally offline.

## 4. Control Plane

### 4.1 Project Memory
Purpose: durable verified project state and prior decisions.  
Consumes: verified Mission Control/evidence projections.  
Produces: bounded context for AI Room and planning.  
Authority: memory only; no execution.

### 4.2 AI Room / Council
Purpose: analysis, proposals, architecture review and research suggestions.  
External advice: ChatGPT / DeepSeek only through bounded advisory paths.  
Authority: **proposal only**. It cannot promote strategies, mutate Paper state or issue orders.

### 4.3 Mission
Converts an accepted bounded proposal into a mission contract.

### 4.4 Supervisor / Coordinator
Owns scheduling, dependency ordering, retry boundaries and resource selection. It must
consult the system map before assigning a workload.

### 4.5 Router / Agent Manager
Maps a task to a capability/runner, creates leases and prevents stale or spoofed result
acceptance.

### 4.6 Workers
Research Agent, QA Verifier, cloud workers and physical runners execute only leased,
bounded workloads.

### 4.7 Evidence + Independent Verifier
A producer result is not DONE until independent evidence verification succeeds.
Producer and verifier must remain separate trust roles.

## 5. Data and Market Plane

### Bybit
Canonical primary market reference and Demo/Paper execution identity. Public/replay
data may feed research. **No Live authority.**

### LBank
Backup/secondary Research market-data source. It can preserve research continuity when
the primary public feed is unavailable, but cannot silently change Bybit execution semantics.

### Bitget
Requested backup Research source. Treat as **not active until current-main implementation,
provenance and tests are verified**. It must remain Research-only when added.

### TradingView
Reference/visual/AI context only unless a separately verified data contract is added.
It is not an execution authority.

All datasets entering Research must pass provenance, timestamp, gap/quality and
look-ahead checks before becoming canonical input.

## 6. Research Plane

```text
Canonical Data
   -> Data Intelligence / Regime
   -> Strategy Finder
   -> Reviewed mechanism grammar
   -> Mechanism Factory / Generator
   -> Training-only ranking
   -> Multi-pair + Multi-timeframe backtest
   -> Validation
   -> Conservative + Stress replay
   -> Independent QA
   -> Qualification
   -> Candidate OR Reject
```

Rules:

- no arbitrary minimum trade-count gate;
- no selection winner chosen from validation/test;
- no parameter/text variant may pose as a new mechanism;
- no arbitrary Python/eval/exec generated strategy code;
- Generator may propose bounded declarative contracts only;
- a negative result returns to Research; it is not hidden;
- independent QA is mandatory;
- qualification is distinct from research success;
- Research has no automatic Demo promotion authority.

## 7. Paper / Runtime Plane

```text
Qualified Candidate
  -> Decision proposal
  -> Deterministic Risk
  -> Paper intent
  -> Simulated fill
  -> Append-only Paper event
  -> Position / PnL / SL / TP / history
  -> Protective Exit
  -> Reconciliation
  -> Performance / Drift
```

### Single-writer rule
Only Laptop 1 is the normal writer of the owner Paper state. Laptop 2 must not write
the same Paper journal concurrently.

### Protective Exit
May reduce/close a Paper position when deterministic protective conditions are met.
It may not open, reverse, promote or submit Live orders.

### Paper Event Store
Append-only, digest-bound and replayable. UI state must be a projection of this durable
state rather than an independent source of truth.

## 8. Product and observability

- **Desktop UI:** primary owner interface on Laptop 1.
- **Product Web API:** authenticated local/read-model surface.
- **Mission Control:** projection of verified task/resource/strategy/Paper/evidence state.
- **Mobile:** observation/control surface only within the same authenticated Paper boundary.
- **Remote Desktop Commander / Tailscale:** operations and recovery transport; never source of truth.

## 9. Failover model

Normal state:

```text
Laptop 1:
  Local PRIMARY
  Bybit WSL PRIMARY
  Paper PRIMARY
  Windows DR READY

Laptop 2:
  Research PRIMARY
  Local Failover STANDBY
  Bybit Failover STANDBY
  Research Secondary OFF
```

Failover activation must be based on verified health loss, not a stale UI indicator.
When the primary returns stably, the failover listener must stop and return to standby.

The following states are architecture violations:

- two concurrent Paper writers;
- primary + failover Local runner permanently active for the same purpose;
- primary + failover Bybit runner permanently active for the same purpose;
- two equivalent Research primaries without an explicit sharding contract;
- DR runner being treated as free generic capacity;
- a failover changing the authority boundary.

## 10. GitHub / CI role

GitHub is the code/evidence source of truth and orchestration surface. It is **not**
the runtime Paper database.

Cloud workflows own:

- PR checks;
- build verification;
- workflow permission policy;
- exact-head artifacts;
- independent verification;
- coordinator state transitions;
- bounded research orchestration;
- failure triage.

Physical runners are used only when the workload genuinely requires the corresponding
machine/network capability.

## 11. New Work Architecture Gate

Before any new work begins, NEXUS must answer:

1. **Node:** Which exact System Map node owns this work?
2. **Existing capability:** Is this already implemented somewhere?
3. **Problem:** Is this a defect, extension, missing edge, deployment issue or genuinely new component?
4. **Upstream:** What produces its input?
5. **Downstream:** What consumes its output?
6. **Owner:** GitHub cloud, Laptop 1, Laptop 2, Agent, or verifier?
7. **Authority:** What is it allowed to change? What is explicitly forbidden?
8. **Evidence:** What test/artifact proves completion?
9. **Rollback:** How is the previous verified state preserved?
10. **Topology impact:** Does the map itself need to change?

If any mandatory answer is missing, the task stays **UNMAPPED** and must not be
implemented blindly.

## 12. Status vocabulary

- **VERIFIED** — implemented and independently evidenced.
- **ACTIVE** — currently running/owned by a resource.
- **STANDBY** — configured but intentionally not active.
- **INTEGRATING** — implemented but not yet fully accepted downstream.
- **PLANNED** — approved direction, not yet implemented.
- **BLOCKED** — dependency prevents safe progress.
- **REJECTED** — tested and rejected by Research/QA/Qualification.
- **UNMAPPED** — no architecture owner; implementation forbidden until mapped.

## 13. Roadmap layers

### Layer A — Stabilize
Keep runtime, Paper single-writer, research runner routing, recovery and exact-head CI stable.

### Layer B — Complete Research autonomy
Strategy Finder -> Generator -> Backtest -> Independent QA -> Qualification must advance
without recycling old mechanisms or bypassing gates.

### Layer C — Complete professional Paper surface
Bind actual ProductRuntime journal, positions, PnL, stops/targets, history and performance
to the same durable state shown in Desktop/Mobile.

### Layer D — Data resilience
Bybit remains canonical; backup Research data sources get explicit provenance and
source-switch rules, never implicit execution substitution.

### Layer E — Product polish
Professional Data/Market, Strategy Research, AI Room, Paper and evidence views; mobile
observability after desktop/runtime contracts are stable.

## 14. Canonical companion files

- `docs/PROJECT_MAP.md` — repository navigation and historical lane ownership.
- `config/nexus-integration-registry.json` — logical producer/consumer contracts.
- `config/nexus-execution-contract.json` — mandatory pre-execution checklist.
- `config/nexus-deployment-topology.json` — machine/runner placement and routing.
- `docs/NEXUS_MASTER_SYSTEM_MAP.md` — this operational architecture.

Every future NEXUS task must be mapped to these contracts before implementation.
