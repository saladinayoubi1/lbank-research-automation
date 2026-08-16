# NEXUS Phase 4 Authority Matrix

Parent: #510
Version: `phase4-authority/v1`

| Component | Read | Propose | Reversible bounded write | Paper execution authority | Risk-policy authority | Live/production/credential authority |
|---|---:|---:|---:|---:|---:|---:|
| Dashboard UI | yes | yes | via validated command path only | no | no | no |
| AI Chat Room | yes | yes | only when L2/L3 policy explicitly allows | no | no | no |
| Specialist Agents | scoped | yes | scoped, reversible, policy-bounded | no | no | no |
| DeepSeek / auxiliary provider | scoped | yes | no direct domain write | no | no | no |
| Strategy Lab | yes | signal proposal | no | no | no | no |
| Decision Engine | yes | action proposal | no | no | no | no |
| Deterministic Risk Engine | yes | decision/rejection | policy state transitions | final eligibility gate for paper commands | owns active deterministic risk enforcement | no |
| Paper Execution | approved command only | no | deterministic demo state transition | yes, paper/demo only after Risk approval | no | no |
| Event Store / Portfolio | validated events | no | append/replay under schema/integrity rules | no | no | no |
| Config / Registry | yes | version proposal | versioned activation under policy | no | no | no |
| Mission Queue | task metadata | schedule/propose | bounded task lifecycle | no | no | no |
| Human owner | yes | yes | yes | may authorize paper changes | may approve policy changes | L4 only; outside Phase 4 for live/production/credentials |

## L0-L4 semantics
- L0 Observe: read/inspect only.
- L1 Propose: produce structured recommendation/draft; no mutation.
- L2 Execute reversible bounded actions: only explicit allowlisted actions with rollback and audit.
- L3 Autonomous bounded workflow: only workflows pre-authorized by versioned policy, with deterministic validators, resource limits, idempotency and circuit breakers.
- L4 Owner-required: credentials, billing-impacting actions, signing, production promotion/deployment, live financial execution and any irreversible authority escalation.

Phase 4 does not authorize the L4 live/production actions listed above. Human ownership does not convert them into Phase 4 scope.

## Escalation rule
No component may increase its own authority. Authority changes require an explicit versioned policy/config change, independent validation, test evidence and normal reviewed merge controls. Stale/conflicting authority state fails closed.
