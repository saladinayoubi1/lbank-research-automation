# ADR-008: Event-driven CI failure triage

- Version: 1.1.0
- Status: Proposed
- Scope: `.github/workflows/nexus-event-driven-failure-triage.yml`
- Authority: evidence/triage only; never merge, release, deployment, credential, signing, billing, trading, or production authority.

## Context

NEXUS needs low-latency evidence when selected CI workflows fail. `workflow_run` is intentionally privileged relative to an untrusted triggering workflow, so the design must assume attacker-influenced event metadata and must not execute triggering-branch code or artifacts. Because the issue body becomes durable evidence consumed by humans and automation, display metadata must not be able to inject misleading Markdown structure.

## Decision

Use a narrow `workflow_run` listener for an explicit workflow-name allow-list and failure-like conclusions only. Repeat the workflow-name allow-list at the privileged job gate as defense in depth, then validate required event fields again inside the write-capable script before any API call. Reject malformed or non-allow-listed metadata with no issue write. Sanitize attacker-influenced display fields before Markdown rendering.

Grant `contents:read`, `actions:read`, and `issues:write` solely to create/update fail-closed evidence issues. Pin every third-party action to a reviewed full commit SHA. The workflow must not checkout triggering code, execute artifacts, consume caches from the triggering run, evaluate event metadata as code, or infer merge/release authorization from a triage issue.

## Threat model

### Assets
Repository integrity, CI evidence integrity, issue tracker integrity, release/merge decisions, secrets and token authority, and the semantic integrity of durable incident evidence.

### Actors
Repository maintainers; GitHub Actions control plane; contributors controlling PR branches and some workflow metadata; compromised third-party action publisher; autonomous NEXUS workers/reviewers.

External AI workers/reviewers are advisory actors only. They do not own credentials and do not gain merge, release, policy, or production authority from this workflow or its issue output.

### Trust boundaries
1. Triggering workflow -> privileged `workflow_run` event.
2. GitHub event metadata -> privileged job predicate.
3. Event metadata -> issue body/title construction.
4. Third-party action code -> repository-scoped token.
5. Triage evidence -> downstream human/automation decisions.
6. External AI recommendation -> deterministic repository policy and CI gates.

## Abuse cases

- A malicious PR causes a failing run and injects crafted branch metadata containing line breaks, backticks, or misleading Markdown.
- A non-allow-listed workflow or successful run attempts to create evidence.
- Missing, malformed, or contradictory event fields reach the write-capable code path.
- Duplicate event delivery creates issue spam or divergent evidence.
- A compromised mutable action tag gains `issues:write` authority.
- A future edit adds checkout/artifact execution and turns untrusted input into privileged code execution.
- Triage evidence or an AI-generated interpretation of it is misread as merge/release approval.

## Deny-by-default policy

The workflow performs no write unless the source workflow is allow-listed and the conclusion is one of `failure`, `cancelled`, `timed_out`, or `action_required`. The allow-list is enforced both by the event subscription and by the privileged job predicate. Before any issue API call, the script must independently reject missing or malformed required fields, non-allow-listed workflow names, non-failure conclusions, invalid full-length hexadecimal head SHAs, invalid run URLs, and invalid run-attempt values.

Unknown workflow names, neutral/success/skipped conclusions, malformed metadata, or ambiguous authority must result in no privileged side effect. Attacker-influenced display fields are normalized before Markdown rendering. The workflow may write only issue evidence; all release/merge/trading/credential authority remains denied.

## Verification

Positive tests must prove the expected workflow allow-list and failure-like conclusions are present at both trigger/job and script gates, and that repeated delivery maps to the same marker key. Negative tests must prove success/neutral/skipped/unknown workflow events cannot satisfy the privileged job predicate. Malformed-input tests must prove validation occurs before any issue API call and returns without writing. Injection tests must prove branch/event display metadata is sanitized before Markdown rendering. Bypass tests must prove the workflow contains no checkout, artifact execution, triggering-run cache consumption, shell interpolation of untrusted metadata, or mutable third-party action reference. Tests also assert the exact permission set and full-SHA pin.

These are repository-level regression controls, not proof of GitHub control-plane behavior. Real `workflow_run` delivery still requires a bounded post-merge canary after the listener exists on the default branch.

## Rollback and recovery

Rollback by disabling/removing the workflow and reverting this ADR/policy tuple. Preserve already-created triage issues as historical evidence, but do not treat them as current authorization. Restore the previous-known-good workflow permissions policy, then re-run exact-head CI before re-enabling. If an abuse, evidence-spoofing, or false-positive incident occurs, quarantine newly created triage evidence until the root cause is identified and the event-to-issue transformation has been revalidated.

## Obsolescence triggers

Re-review this ADR when GitHub changes `workflow_run`, `GITHUB_TOKEN`, repository ruleset, cache/artifact trust semantics, action pinning guidance, event payload shape, or when the pinned action is deprecated/advised vulnerable. Also re-review after any false-positive, privilege escalation, evidence spoofing, recursion incident, or change that gives an AI worker additional authority.

NIST published SP 800-218 Rev. 1 / SSDF Version 1.2 as a draft in December 2025. Re-review this ADR when that revision becomes final or materially changes relevant practices. NIST SP 800-218A is already final for generative-AI and dual-use foundation-model development; use it as an additional governance reference when NEXUS introduces AI-produced software-development artifacts or broader AI decision authority.

## Evidence triangulation

- Official standard: NIST SP 800-218 SSDF v1.1 (final, February 2022) recommends integrating secure development practices into the SDLC, mitigating exploitation impact, and addressing vulnerability root causes: https://csrc.nist.gov/pubs/sp/800/218/final
- Official AI-governance profile: NIST SP 800-218A (final, July 2024) augments SSDF with practices for generative AI and dual-use foundation models. NIST also lists SP 800-218 Rev. 1 / SSDF v1.2 as a December 2025 draft, so it is evidence for future review rather than a replacement for the current final baseline: https://csrc.nist.gov/projects/ssdf/publications
- Independent research: Torres-Arias et al., *in-toto* (USENIX Security 2019), shows why software-supply-chain evidence should be explicitly bound and verifiable across independent actors: https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias
- Implementation guidance: GitHub Secure Use guidance recommends least privilege and full-length commit SHA pinning for immutable third-party action references; GitHub documents that `workflow_run` can operate with elevated token/secrets relative to the triggering workflow: https://docs.github.com/en/actions/security-guides/security-hardening-for-github-actions and https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#workflow_run
- Incident evidence: Codecov's April 2021 Bash Uploader compromise extracted environment variables from CI environments; the incident was detected when a customer noticed a SHA-256 mismatch, reinforcing immutable-reference/integrity verification and least-privilege lessons: https://about.codecov.io/apr-2021-post-mortem/
- Limitation/opposing view: this design does not checkout untrusted code and limits write authority to issues, materially reducing exploitability. It still cannot eliminate GitHub control-plane compromise, malicious behavior inside the reviewed pinned action commit, misleading but syntactically valid event values supplied by the platform, or pre-merge proof of actual `workflow_run` delivery because a new listener must exist on the default branch to receive such events.

## Residual risk

A compromised GitHub control plane or reviewed pinned action commit remains outside this control. Issue evidence is advisory telemetry only. Sanitization protects evidence structure, not the truth of a platform-supplied value. A bounded post-merge canary is required to validate real event delivery; failure of that canary requires rollback or a new reviewed ADR revision, never gate weakening.
