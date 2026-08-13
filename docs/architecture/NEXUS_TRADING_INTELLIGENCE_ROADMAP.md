# NEXUS Trading Intelligence Roadmap

Status: durable roadmap companion to `NEXUS_TRADING_INTELLIGENCE_SPEC.md`.
Authority boundary: Research / Backtest / Validation / Shadow-Paper only. This roadmap creates no live-trading, production, credential, billing, signing, or irreversible authority.

## Phase 3 — Infrastructure closure only
Phase 3 remains governed only by the existing six frozen exit gates. Trading-intelligence roadmap work must not create new Phase-3 blockers or expand the frozen scope.

Phase-3 strategy/research work may continue in parallel, but strategy profitability is not a Phase-3 exit requirement.

## Phase 4 — CORE Trading Intelligence
Goal: make the recovered AI Trading Discussion Room and the minimum useful trading-intelligence loop executable and verifiable.

Core flow:

```text
Observe
  ↓
Opportunity Scanner
  ↓
Explicit Hypothesis
  ↓
Regime + Uncertainty
  ↓
Structured Multi-AI Debate + Red Team
  ↓
Execution / Portfolio Feasibility
  ↓
Deterministic Data + Risk Gates
  ↓
Backtest / Replay Foundation
  ↓
Shadow / Paper Execution
  ↓
Decision + Experiment Log
  ↓
Attribution + Validated Knowledge
```

Phase-4 scope:
- valid, provenanced market data;
- multiple strategy families rather than one rare signal path;
- Opportunity Scanner across eligible symbols/timeframes/regimes;
- explicit falsifiable hypotheses and deterministic strategy rules;
- Market Regime Detector with uncertainty/ambiguous-state handling;
- structured AI Trading Discussion Room;
- blind independent proposals before debate where practical;
- Red-Team / contradiction challenge;
- Trade Thesis Contract;
- execution realism: fees, spread, slippage, funding, latency, leverage/liquidation where applicable;
- portfolio/exposure check at the minimum safe level;
- deterministic final Risk/Data/Authority gates;
- deterministic backtest and OOS/walk-forward requirements;
- Replay foundation where feasible;
- automatic Shadow/Paper execution only;
- Decision Log and Experiment Registry;
- Attribution Engine foundation;
- Knowledge Lifecycle foundation;
- activity/sample-size gate so ultra-sparse strategies do not pass from a few favorable trades.

Phase-4 completion does NOT require advanced self-evolution. It requires the CORE loop to execute, pass acceptance tests, and persist durable evidence.

## Phase 5 — ADVANCED Trading Intelligence
Goal: improve calibration, diversification, robustness, replay realism and adaptive evaluation after the CORE loop is proven.

Planned capabilities:
- Portfolio Intelligence and strategy-correlation graph;
- Agent Skill Matrix and regime-specific calibration;
- Ensemble Diversity Score to detect correlated/groupthink opinions;
- full Replay Laboratory with future-information isolation;
- Champion / Challenger strategy and model comparison;
- counterfactual analysis;
- causal/decision attribution refinement;
- Drift Monitor for strategy, regime, data, costs and calibration;
- Scenario Library for liquidity shocks, spread expansion, funding extremes, stale/corrupt feeds and event transitions;
- opportunity-cost / missed-opportunity analysis without hindsight leakage;
- Regime Transition Detector;
- Strategy Lifecycle Manager: Idea → Experimental → Candidate → Shadow → Active Paper → Degraded/Suspended/Retired;
- Human-readable Decision Cards;
- independent Agent/model health, provenance and quarantine controls.

## Phase 6 — EXPERIMENTAL / Evolution
Goal: controlled self-improvement without uncontrolled self-modification or parameter mining.

Planned experimental capabilities:
- Evolution Engine advanced mechanisms;
- Strategy DNA and Novelty Guard;
- strategy recombination;
- adaptive routing / voting;
- meta-learning experiments;
- dynamic role/executor selection;
- exploration-budget allocation across new ideas, refinement and replication;
- advanced Champion/Challenger promotion;
- automated strategy invention only through preregistered deterministic experiments.

Every generated strategy returns through:

```text
Hypothesis
  ↓
Preregistered experiment
  ↓
Backtest
  ↓
OOS / Walk-forward
  ↓
Robustness / Replay
  ↓
Shadow / Paper
  ↓
Promote / Reject / Modify
```

No Evolution component may overwrite an active champion directly.

## Permanent design constraints

### Patch-friendly / evolvable architecture
Core contracts stay stable while implementations remain replaceable:

```text
Stable Contract / Interface
  ↓
Versioned Policy + Schema
  ↓
Versioned Implementation
  ↓
Candidate vNext
  ↓
Acceptance + Compatibility Tests
  ↓
Backtest / Replay / Shadow Comparison
  ↓
Promote OR Roll Back
```

Rules:
- all material Strategy, Agent, Model, Regime, Router and Decision components carry version IDs;
- configs/policies are explicit and versioned;
- material behavior changes create a candidate version rather than silently patching the active implementation;
- feature flags isolate experimental capabilities;
- migrations/backward-compatibility rules exist for schema changes;
- acceptance criteria and rollback path are required for material changes;
- better future ideas are expected and should be tested side-by-side rather than blocked by this roadmap.

### Consolidation rules
Avoid overlapping subsystems:
- Meta-Controller + Decision Complexity Router = one Routing subsystem;
- Decision Attribution + Performance Attribution + Causal Review = one Attribution Engine;
- Observation/Experiment/Failed-Idea/Validated/Deprecated memories = one Knowledge Lifecycle with distinct states;
- Red-Team Trader + contradiction challenge = one adversarial review stage.

### Complexity control
Logical roles do not imply permanently separate LLMs. Use deterministic code where possible, bounded inexpensive models for routine advisory work, specialist Agents only when useful, and deeper reasoning only for high-value/uncertain cases.

Routing levels:
- FAST — validated setup, low uncertainty;
- STANDARD — normal committee path;
- DEEP — new strategy, regime transition, event shock, high disagreement.

### Three invariants
1. AI never substitutes for evidence.
2. Profit never substitutes for validation.
3. Consensus never overrides deterministic data/risk/authority controls.

## Definition of Done
No roadmap component is DONE because it is documented, connected, coded or configured.

DONE requires:

```text
Implemented / Executed
+
Real Verification
+
Acceptance Criteria Met
+
Durable Evidence
```

Otherwise use UNVERIFIED or BLOCKED with the exact reason.

## Preservation rule
Future Project Memory, STATE/handoff and roadmap summaries must reference both:
- `docs/architecture/NEXUS_TRADING_INTELLIGENCE_SPEC.md`
- `docs/architecture/NEXUS_TRADING_INTELLIGENCE_ROADMAP.md`

Phase mapping is durable unless explicitly changed by a versioned owner/architecture decision:
- Phase 3: frozen infrastructure exit gates only;
- Phase 4: CORE Trading Intelligence + AI Trading Discussion Room;
- Phase 5: ADVANCED intelligence, calibration, portfolio and replay;
- Phase 6: EXPERIMENTAL Evolution and meta-learning.
