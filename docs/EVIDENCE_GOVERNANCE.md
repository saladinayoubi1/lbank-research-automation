# NEXUS Evidence Governance

High-impact architecture decisions must not rely on one website, one model answer, or one unverified claim.

## Decisions covered

This process is mandatory for decisions that materially affect security, privacy, authorization, data retention, network access, secrets, AI tool use, reliability, recovery, supply chain, production deployment, or irreversible architecture.

## Minimum evidence set

Before acceptance, an ADR normally requires:

1. one current authoritative standard or official platform requirement;
2. one independent academic source, systematic review, or rigorous thesis;
3. one implementation, vulnerability, exploit-class, or incident source;
4. one limitation, dissenting result, conflicting source, or explicit statement of uncertainty.

A missing category must be explained. Blogs, vendor marketing, and model outputs may locate sources but cannot be the sole justification.

## Decision gates

```text
Research question
    ↓
Threat model and system boundary
    ↓
Evidence triangulation
    ↓
Conflicts and assumptions recorded
    ↓
Options compared
    ↓
Reversible prototype
    ↓
Positive + negative + bypass tests
    ↓
Cross-platform validation where applicable
    ↓
Residual risk and rollback recorded
    ↓
Architecture decision accepted
```

## Required ADR fields

Every covered ADR records applicability, assumptions, evidence quality, conflicts, selected control, rejected alternatives, residual risk, confidence, verification method, review date, and obsolescence triggers.

## Architecture lock rule

A critical control cannot be architecture-locked until:

- the evidence set is complete or gaps are explicitly accepted;
- enforcement exists outside prompts and documentation;
- positive and negative tests pass;
- relevant bypass tests pass;
- rollback or migration exists;
- platform-specific limitations are visible;
- CI preserves the verified behavior.

## Proportionality

Low-risk reversible work may proceed with lighter evidence. It must not silently become a critical dependency. Evidence depth increases with privilege, irreversibility, data sensitivity, external impact, and blast radius.

## Review and expiry

Accepted ADRs receive a review date and obsolescence triggers. A new vulnerability, platform change, failed security test, incident, or contradictory high-quality evidence reopens the decision.

## Verification artifacts

Evidence is not complete until translated into one or more of: threat models, policy schemas, narrow APIs, tests, CI gates, audit signals, recovery exercises, or artifact verification.
