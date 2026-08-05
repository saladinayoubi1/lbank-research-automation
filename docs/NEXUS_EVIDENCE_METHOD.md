# NEXUS Evidence-Driven Engineering Method

## Purpose

NEXUS must not base critical architecture, security, privacy, reliability, or AI-governance decisions on a single article, vendor claim, blog post, or model response. Important decisions require evidence triangulation, implementation proof, and verification.

## Source hierarchy

Use the strongest applicable sources first:

1. Current standards and official guidance from recognized bodies such as NIST, OWASP, ISO/IEC, IETF, CIS, ENISA, CISA, platform vendors, and operating-system security documentation.
2. Peer-reviewed journal and conference papers from reputable publishers and societies.
3. Systematic literature reviews, meta-analyses, surveys, and well-scoped theses or dissertations with transparent methodology.
4. Reproducible security research, public incident analyses, vulnerability databases, and mature open-source project documentation.
5. Vendor documentation and technical blogs only as implementation-specific secondary evidence.
6. Informal posts, forums, and model-generated content only for discovery, never as sole justification.

## Minimum evidence rule

For every high-impact decision, collect at least:

- one authoritative standard or official primary source;
- one independent peer-reviewed or academically rigorous source;
- one implementation-oriented source, incident record, benchmark, or reproducible test;
- one documented dissenting view, limitation, or failure mode when available.

A decision may proceed with fewer sources only when the matter is narrow, platform-specific, and covered directly by authoritative documentation. The exception and rationale must be recorded.

## Evidence record

Each architecture decision record must include:

- question and scope;
- assumptions;
- sources and publication dates;
- source type and authority;
- agreement and disagreement between sources;
- applicability to NEXUS;
- chosen control or design;
- rejected alternatives;
- expected benefits;
- risks and residual uncertainty;
- implementation evidence;
- test or verification method;
- review date and obsolescence trigger.

## Research workflow

1. Define the threat, requirement, or design question precisely.
2. Search across standards, academic databases, official documentation, vulnerability records, and incident reports.
3. Exclude irrelevant, duplicated, outdated, unverifiable, or commercially biased claims.
4. Compare conclusions, assumptions, environments, and limitations.
5. Build a threat model or decision matrix.
6. Select the least-complex control that satisfies the strongest applicable requirements.
7. Implement behind a reversible branch or feature boundary.
8. Add automated tests, negative tests, abuse cases, and CI gates.
9. Verify on supported platforms and inspect artifacts.
10. Record residual risk and schedule review.

## Security-specific rules

- Security claims are not accepted without testable controls.
- Configuration guidance must be tested against bypass paths, not only normal use.
- Prompt instructions alone never count as security boundaries.
- OS-level enforcement, least privilege, deny-by-default policy, canonical path checks, process isolation, network egress controls, and fail-closed behavior are preferred over advisory rules.
- Threat models must cover direct access, indirect access, alternate tools, plugins, shell execution, symbolic links, archives, caches, screenshots, OCR, clipboard, IPC, child processes, network exfiltration, prompt injection, phishing, and supply-chain compromise.
- Offensive testing is restricted to explicitly authorized repository-owned test targets and isolated environments.

## Confidence levels

- High: multiple independent strong sources agree and implementation tests pass.
- Medium: evidence is credible but incomplete, environment-specific, or not fully validated.
- Low: evidence is preliminary, conflicting, or based mainly on analogy. Low-confidence controls cannot protect critical assets without additional safeguards.

## Change control

A foundational design is not locked merely because it is documented. It becomes eligible for architecture lock only after:

- evidence review;
- threat modeling;
- implementation;
- automated verification;
- cross-platform validation where applicable;
- review of bypasses and failure modes;
- documented rollback;
- no unresolved critical risks.

## Continuous review

Evidence must be revisited when:

- a relevant standard changes;
- a new platform or provider is added;
- a serious vulnerability or incident affects the design;
- tests expose an undocumented bypass;
- assumptions change;
- the control reaches its scheduled review date.

## Outcome

NEXUS decisions must be traceable from evidence to architecture, from architecture to code, and from code to verified behavior. Documentation without enforcement is incomplete; enforcement without evidence is unjustified; tests without adversarial cases are insufficient.
