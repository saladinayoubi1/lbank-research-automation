# NEXUS Trading Intelligence — Durable Specification

Status: recovered from archived NEXUS chat history and normalized for durable project use.
Scope: Research / Backtest / Validation / Shadow-Paper only. No live trading authority is created by this document.

## 1. Purpose

NEXUS is not intended to be a single-indicator bot or a single-LLM decision maker. Its trading intelligence is a multi-agent, evidence-driven, self-evaluating research system that converts research and market observations into deterministic hypotheses, validates them, debates candidate opportunities, applies deterministic risk controls, executes only in paper/shadow mode, and feeds observed outcomes back into research and strategy generation.

Core principle:

> AI is not merely a knowledge memorizer or signal generator. It acts as a bounded researcher, strategy creator, critic and decision contributor; deterministic risk controls retain final authority.

## 2. Canonical architecture

```text
                 NEXUS TRADING INTELLIGENCE
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
  Research Lab        Strategy Lab        Learning Lab
        │                   │                   │
        └───────────────────┼───────────────────┘
                            ▼
                  Evolution Engine
                            │
                            ▼
                  Strategy Candidates
                            │
                            ▼
                 Validation Pipeline
                            │
                            ▼
                 Market Regime Detector
                            │
                            ▼
                    Strategy Selector
                            │
                            ▼
               Multi-AI Decision Committee
             ┌──────────────┼──────────────┐
             │              │              │
       Technical AI    Research AI      News AI
             │              │              │
             └──────┐   Risk AI   ┌────────┘
                    └──────┬──────┘
                           ▼
                     Decision AI
                           │
                    Consensus/Score
                           │
                           ▼
               Deterministic Risk Manager
                           │
                    PASS / REJECT
                           │
                           ▼
                  Paper Trading Engine
                           │
                           ▼
                Performance & Feedback
                           │
                           ▼
                 Root-Cause Analysis
                           │
                           ▼
                   AI Review Meeting
                           │
                           ▼
                 Knowledge Base Update
                           │
                           └──────────────↺
```

This refines the repository-wide modular direction:

```text
Market Core
→ Crypto/FX adapters
→ Research Lab
→ Strategy Lab
→ Regime Detector
→ Decision Engine
→ Risk Engine
→ Paper/Shadow Execution
→ Dashboard
```

## 3. Research Lab

Research Lab gathers and evaluates books, papers, official documentation, institutional research, market-structure evidence and implementation evidence.

It must not stop at summarization. Its required output is a testable hypothesis.

```text
Books / Papers / Evidence
          ↓
   Extract market claim
          ↓
 Convert to explicit hypothesis
          ↓
 Deterministic experiment rules
          ↓
 Backtest
          ↓
 OOS / Walk-Forward
          ↓
 Paper / Shadow
          ↓
 Evidence Review
```

For high-impact claims, evidence should be triangulated where proportionate across authoritative sources, independent academic evidence, implementation/incident evidence, and limitations/opposing evidence.

## 4. Strategy Lab

Strategy Lab converts evidence and observed market behavior into explicit strategy candidates.

Responsibilities include:
- generate strategy hypotheses;
- combine existing strategy ideas when justified;
- select strategy families appropriate to market conditions;
- version strategy definitions;
- retire or downgrade weak candidates;
- preserve failure modes and invalidation criteria;
- avoid accepting a strategy from headline return alone.

Each strategy family must define at least:
1. evidence-backed rationale;
2. explicit deterministic hypothesis;
3. deterministic entry rules;
4. deterministic exit rules;
5. sizing/risk rules;
6. exact data semantics;
7. fees and transaction costs;
8. slippage;
9. funding where applicable;
10. latency/execution assumptions;
11. leverage/liquidation realism where applicable;
12. benchmark;
13. OOS / walk-forward validation;
14. regime robustness;
15. symbol/timeframe robustness;
16. parameter perturbation;
17. drawdown and downside behavior;
18. statistical uncertainty;
19. failure modes;
20. invalidation/kill criteria;
21. reproducibility requirements;
22. activity/sample-size eligibility so statistically sparse candidates do not pass solely because of a few good trades.

Promotion remains staged:

```text
Research → Candidate → Validation → Shadow/Paper
```

No direct Research → Live path exists.

## 5. Market Regime Detector

Before strategy selection, NEXUS classifies current market context.

Relevant dimensions recovered from the original design include:
- trending;
- ranging;
- high volatility;
- low volatility;
- news-driven/event-driven;
- low liquidity;
- manipulation/liquidity-sweep risk;
- unstable/ambiguous regime.

Example adaptive behavior:

```text
Trend → trend-following candidate set
Range → mean-reversion candidate set
High volatility → breakout or reduced-risk candidate set
Major event/news risk → possibly NO-TRADE
Ambiguous regime → reduce confidence or fail closed
```

No-trade is a valid decision. The objective is not continuous market exposure; it is selecting an appropriate behavior for each regime while maintaining enough sample activity for strategies to be statistically testable.

## 6. Multi-AI Decision Committee / Trading Discussion Room

This is the recovered core of the planned AI discussion room.

The room is not generic chat. Its primary purposes are:
- strategy discovery;
- trade-opportunity debate;
- disagreement preservation;
- adversarial review;
- conversion of qualitative reasoning into deterministic testable rules;
- post-trade critique and learning.

Canonical participant roles:

### Technical AI
Analyzes market structure, trend, momentum, volatility, price action, technical state and implementation-relevant chart context.

### Research AI
Provides evidence from the research library, papers, books, market microstructure literature and previously validated NEXUS experiments.

### News / Event AI
Assesses event risk, macro/news context and whether a market move may be event-driven. It must distinguish verified information from uncertain narratives.

### Risk AI
Challenges sizing, stop placement, downside, drawdown exposure, liquidity assumptions, leverage/liquidation risk and portfolio concentration.

### Decision AI / Committee Chair
Combines structured opinions without erasing disagreement, produces the decision record and proposes the next deterministic action or experiment.

### DeepSeek / auxiliary models
May participate as bounded advisory critics, second-opinion reviewers, edge-case finders or log/test reviewers under existing hard-budget and authority restrictions. They never have merge, risk-policy or financial authority.

### Independent Agent / reviewer
Where useful, a second independent Agent should verify a committee conclusion before it is accepted as evidence.

## 7. Committee debate contract

A trade/opportunity discussion should not collapse into a single free-form answer. Each participant should return structured fields such as:

```text
agent_role
market_snapshot_id
regime_view
candidate_strategy
bull_case
bear_case
key_evidence
missing_evidence
assumptions
risk_flags
confidence
invalidation_conditions
suggested_test
```

The final committee record may include:

```text
direction / no-trade
strategy_id
confidence_score
risk_score
entry_condition
exit_condition
stop_condition
take_profit_condition
position_sizing_proposal
dissent_summary
uncertainties
evidence_refs
test_required
```

Any language-model confidence is advisory, not calibrated probability by default.

## 8. Disagreement is a feature

The original concept explicitly benefits from agents disagreeing.

Examples:
- Research AI finds historical evidence for a setup;
- Technical AI objects because current regime is inconsistent;
- News AI identifies event risk;
- Risk AI rejects sizing even if direction is plausible;
- Decision AI records the disagreement rather than fabricating consensus.

Consensus must never mean deleting dissent. Durable decision evidence must preserve:
- which agent disagreed;
- why;
- what evidence would resolve the dispute;
- whether the final decision proceeded despite dissent.

## 9. Deterministic Risk Manager — final authority

The risk layer is not another conversational vote.

Even if all AI contributors favor a trade:

```text
AI Committee → candidate BUY
                 ↓
      Deterministic Risk Manager
                 ↓
        Risk gate fails
                 ↓
              REJECT
```

LLM or Agent output must never override deterministic risk, data-integrity, authority or safety gates.

## 10. Paper Trading Engine

Approved candidates may be executed only in research/backtest/shadow/paper scope unless the owner explicitly authorizes a future higher-risk stage.

Paper execution should capture realistic assumptions where applicable:
- fees;
- bid/ask or effective spread;
- slippage;
- funding;
- latency;
- liquidity constraints;
- leverage;
- liquidation;
- partial/failed fill assumptions if modeled;
- position sizing;
- stop and exit behavior.

No paper result may be represented as verified live-market profitability.

## 11. Decision Log

Every candidate trade/experiment must be reconstructable.

Minimum durable decision record:

```text
market/data snapshot identity
regime classification
strategy version
agent opinions
supporting evidence
opposing evidence
dissent
confidence / uncertainty
risk decision
entry reason
exit reason
execution assumptions
result
post-trade attribution
```

The Decision Log becomes input to the Learning Lab; it is not merely a human-readable journal.

## 12. Learning Lab

The system must learn from observed outcomes without silently changing production/risk policy.

```text
Decision
   ↓
Paper/Backtest Result
   ↓
Performance Analysis
   ↓
Root-Cause Analysis
   ↓
Proposed Knowledge/Strategy Update
   ↓
Revalidation
```

Questions include:
- Was the strategy hypothesis wrong?
- Was regime classification wrong?
- Did execution costs erase the edge?
- Was entry late?
- Was risk sizing wrong?
- Did news/event context invalidate technical evidence?
- Was the dataset unrepresentative or invalid?
- Was apparent performance caused by leakage, overfitting or sparse samples?

Learning may propose changes, but promoted changes must return through deterministic validation.

## 13. AI self-criticism / review meetings

The recovered design includes periodic internal review meetings after a meaningful sample of trades/experiments. The historic chat used an example such as review after a large trade count; the exact cadence is not frozen and should be selected based on statistical information value rather than an arbitrary fixed number.

Review meeting agenda:
1. wins and losses by strategy;
2. results by regime;
3. performance of each AI role;
4. recurring disagreement patterns;
5. execution-cost failures;
6. false-positive signals;
7. missed opportunities;
8. strategy inactivity / insufficient sample frequency;
9. proposed experiments;
10. rules or strategies to retire.

The output is an experiment backlog, not immediate self-modification.

## 14. Evolution Engine

The Evolution Engine is the strategy-generation loop recovered from the original discussion.

```text
OBSERVE
   ↓
RESEARCH
   ↓
GENERATE
   ↓
TEST
   ↓
COMPARE
   ↓
KEEP / REJECT / MODIFY
   ↓
REPEAT
```

A new strategy may arise from:

```text
Strategy A
   +
Strategy B
   +
New research evidence
   +
Observed market behavior
   ↓
New deterministic candidate
```

It then re-enters the validation pipeline. Evolution does not mean uncontrolled self-modifying trading logic.

## 15. Performance & Feedback Engine

Performance must be decomposed rather than summarized only by total PnL.

Required dimensions include:
- trade performance;
- strategy performance;
- market-regime performance;
- symbol/timeframe performance;
- decision-logic performance;
- individual AI-role usefulness;
- dissent predictive value;
- risk-manager effects;
- execution-cost effects;
- data-quality effects;
- benchmark-relative performance;
- activity/sample-size sufficiency.

Metrics should include drawdown and uncertainty, not only return.

## 16. Strategy activity / sample-frequency principle

The recovered owner intent strongly rejects a system that waits indefinitely for one nearly-perfect setup. NEXUS should evaluate multiple strategy families and regimes rather than optimize for a single rare signal.

However, this does not create a requirement to trade continuously. Instead:
- multiple strategy families compete;
- activity and sample size are explicitly measured;
- statistically sparse candidates are downgraded or rejected unless exceptional evidence justifies them;
- no-trade remains valid when risk/evidence conditions fail;
- frequency must not be manufactured by weakening quality or integrity gates.

## 17. Candidate strategy families

The Discussion Room / Strategy Lab should be capable of researching multiple independent families rather than relying on one EMA crossover or one indicator family, including where evidence supports them:
- trend following;
- momentum;
- breakout;
- mean reversion;
- carry / funding / basis;
- volatility strategies;
- market microstructure / liquidity effects;
- statistical relative-value approaches;
- regime-conditioned hybrids.

Each remains a hypothesis family until validated.

## 18. Data integrity

All strategy intelligence remains subordinate to fail-closed data rules.

Reject or quarantine:
- missing data;
- unexplained gaps;
- duplicates;
- out-of-order data;
- off-grid timestamps;
- stale data;
- invalid OHLC;
- malformed/nonpositive/implausible bars;
- ambiguous source/provenance/timeframe/market semantics.

Never fabricate candles, clamp OHLC, hide gaps or silently substitute exchanges/data namespaces.

## 19. Anti-overfitting requirements

The AI room must not become a parameter-mining engine.

Required defenses:
- preregister important experiment rules where practical;
- exact separation of in-sample and out-of-sample data;
- walk-forward validation;
- robustness across symbols/timeframes/regimes;
- parameter perturbation;
- realistic costs;
- benchmark comparison;
- uncertainty reporting;
- minimum sample/activity checks;
- record rejected variants, not only winners;
- prevent look-ahead, leakage and survivorship bias.

## 20. Relationship to NEXUS autonomous orchestration

The Trading Discussion Room is a Product/Research worker capability, not a replacement for the project Orchestrator.

```text
Owner Goal / Policy
        ↓
NEXUS Orchestrator
        ↓
Durable Mission Queue
        ↓
Trading Research / Discussion tasks
        ↓
Agents / DeepSeek / Runner / CI / Zotero
        ↓
Execute / Debate / Test
        ↓
Independent Verification
        ↓
Persist Evidence
        ↓
Next Task
```

The Orchestrator decides workload assignment and throughput. The AI Trading Committee evaluates market/strategy hypotheses within bounded tasks.

## 21. Tool roles

- Zotero: evidence/reference library and provenance support.
- Agents: parallel research, analysis, coding, test generation and independent review.
- DeepSeek: bounded low-cost advisory critic/second opinion under hard budget controls.
- Laptop/self-hosted runner: local execution, recovery/restart tests and heavier deterministic validation.
- GitHub Actions: independent CI/verification.
- GitHub repository: version control and durable evidence, not an activity generator.

Configured/connected does not mean ACTIVE. A resource is active only after a real workload executes and produces observable evidence.

## 22. Safety / authority boundary

Current authority is strictly:

```text
Research / Backtest / Validation / Shadow-Paper
```

This specification does not authorize:
- live trading;
- real orders;
- production deployment;
- credentials/secrets disclosure or mutation;
- billing/signing authority;
- deposits/withdrawals;
- irreversible financial action.

Any future transition beyond paper/shadow requires explicit owner authority and new validation/controls.

## 23. Definition of Done

No component of this architecture is DONE because it was described, coded, connected or configured.

DONE requires:

```text
Implemented / Executed
        +
Real verification
        +
Acceptance criteria met
        +
Durable evidence
```

Otherwise status must remain UNVERIFIED or BLOCKED with the exact reason.

## 24. Durable design decisions recovered from archived chat

The following ideas are now explicitly preserved because they were at risk of being lost during chat migration:
- Multi-AI Trading Discussion / Decision Committee;
- Research Lab + Strategy Lab + Learning Lab;
- Market Regime Detector before strategy selection;
- strategy discovery, not only signal scoring;
- structured agent disagreement and adversarial debate;
- post-trade AI review meetings;
- performance attribution by strategy/regime/AI/risk/execution;
- Evolution Engine for generating new deterministic candidates;
- Knowledge Base feedback loop;
- deterministic Risk Manager as final risk authority;
- Research → Candidate → Validation → Shadow/Paper promotion;
- multiple strategy families and explicit rejection of statistically useless ultra-sparse strategy candidates;
- no direct live-trading authority.

## 25. Preservation rule

Future handoffs and Project Memory summaries must reference this specification instead of attempting to reconstruct the Trading Intelligence design from raw chat history.

If later evidence contradicts a recovered detail, update this document through a versioned decision/ADR process and record the conflict rather than silently rewriting history.
