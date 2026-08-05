# ADR-003: Deterministic policy gate for the NEXUS Brain Core

- **Status:** accepted for bounded implementation
- **Date:** 2026-08-05
- **Owners:** NEXUS architecture
- **Review date:** 2026-11-05
- **Obsolescence triggers:** NIST AI RMF revision; material agent-security evidence; policy bypass; unauthorized side effect; new production or credential capability; mission-model change

## Context

NEXUS needs a small coordination layer that combines the mission queue and AI Council without turning model output into authority. The failure modes are excessive agency, automation bias, policy bypass, unbounded plans, cross-repository action, and irreversible operations without informed human approval.

## Assumptions

- Model or agent recommendations may be wrong, manipulated, incomplete, or unavailable.
- Repository actions remain mediated by GitHub permissions and existing capability controls.
- Deterministic policy decisions are auditable but do not prove that the underlying recommendation is correct.
- The first implementation emits an approved proposal only; it is not a production execution engine.

## Evidence triangulation

### Authoritative standards and official guidance

1. **NIST AI RMF 1.0, NIST AI 100-1** defines Govern, Map, Measure, and Manage functions; it calls for documented roles, human oversight, risk tolerances, monitoring, go/no-go decisions, and decommissioning processes. https://doi.org/10.6028/NIST.AI.100-1
2. **NIST AI RMF Generative AI Profile, NIST AI 600-1** extends lifecycle risk management to generative systems and emphasizes governance, testing, incident handling, and provenance. https://doi.org/10.6028/NIST.AI.600-1
3. **OWASP LLM06:2025 Excessive Agency** identifies excessive functionality, permissions, and autonomy as root causes of damaging agent actions and recommends minimizing extensions, permissions, and autonomy. https://genai.owasp.org/llmrisk/llm062025-excessive-agency/

### Independent academic evidence

Alon-Barkat and Busuioc, *Human-AI Interactions in Public Sector Decision-Making: Automation Bias and Selective Adherence to Algorithmic Advice*, Journal of Public Administration Research and Theory 33(1), 2023, reports experimental evidence that people may over-rely on algorithmic advice despite warning signals. DOI: 10.1093/jopart/muac007.

### Implementation and incident evidence

Agentic security guidance and vulnerability records consistently show that a model with broad tools can convert hallucination, prompt injection, or ambiguous goals into real side effects. OWASP classifies this as Excessive Agency and documents examples involving unnecessary modification and deletion functions. This is directly applicable because NEXUS coordinates tools and repository changes.

### Limitation and conflicting evidence

- NIST AI RMF is voluntary and non-prescriptive; NIST states that AI RMF 1.0 is being revised and that effectiveness measurement remains developing.
- Human approval is not automatically effective: automation bias can turn approval into rubber-stamping.
- Determinism improves repeatability, not semantic correctness. A deterministic policy can consistently enforce a flawed rule.
- A proposal-only core cannot provide OS-level containment or prevent actions taken through an unmediated external channel.

## Options considered

### A. Let the model select and execute actions directly

- **Benefit:** maximum speed and flexibility.
- **Risk:** model output becomes authority; prompt injection or hallucination can cause high-impact actions.
- **Decision:** rejected.

### B. Human approval for every operation

- **Benefit:** simple accountability boundary.
- **Risk:** approval fatigue, automation bias, and unnecessary delay for reversible low-risk work.
- **Decision:** rejected as universal policy.

### C. Deterministic deny-by-default policy gate with risk-proportionate human approval

- **Benefit:** bounded authority, explicit repository and action allowlists, reproducible decisions, and human gates for high-impact operations.
- **Risk:** policy maintenance cost and residual automation bias.
- **Decision:** selected.

## Decision

The NEXUS Brain Core will:

1. select only an eligible mission from the validated mission queue;
2. require an approving AI Council decision and preserve stability/security vetoes;
3. deny actions and repositories not explicitly allowlisted;
4. enforce plan-step and changed-file limits;
5. require explicit human approval for high-risk or listed sensitive decisions;
6. reject unknown approval categories;
7. emit `proposal_only` rather than directly executing privileged or production effects;
8. fail closed with `defer` when required context, quorum, mission eligibility, or approval is absent.

## Verification plan

- Positive test for an approved low-risk repository proposal.
- Negative tests for unlisted actions and repositories.
- Veto and quorum tests through the AI Council.
- High-risk, billing, and unknown-override tests.
- Plan and file-count boundary tests.
- Policy mutation test proving permissive default is rejected.
- CI validation with Node.js 22.

## Rollback and recovery

The change is configuration and deterministic JavaScript only. Rollback is a commit revert. Existing mission queue and AI Council remain independently usable. No credentials, user data, deployment state, or external resources are modified.

## Residual risk

- Humans may approve unsafe proposals.
- Input risk classification may be wrong or manipulated.
- The gate does not mediate tools outside its call path.
- Repository allowlisting does not replace branch protection, code review, capability enforcement, or CI.
- Policy drift may cause either unsafe approval or excessive deferral.

## Confidence

**Medium.** The control aligns with established risk-governance and least-agency guidance and is directly testable. Confidence is limited until every execution adapter is forced through the gate and human-approval usability is evaluated.
