# ADR-008: Event-driven CI failure triage

- Version: 1.0.0
- Status: Proposed
- Scope: `.github/workflows/nexus-event-driven-failure-triage.yml`
- Authority: evidence/triage only; never merge, release, deployment, credential, signing, billing, trading, or production authority.

## Context

NEXUS needs low-latency evidence when selected CI workflows fail. `workflow_run` is intentionally privileged relative to an untrusted triggering workflow, so the design must assume attacker-controlled metadata and must not execute triggering-branch code or artifacts.

## Decision

Use a narrow `workflow_run` listener for an explicit workflow-name allow-list and failure-like conclusions only. Grant `contents:read`, `actions:read`, and `issues:write` solely to create/update fail-closed evidence issues. Pin every third-party action to a reviewed full commit SHA. The workflow must not checkout triggering code, execute artifacts, consume caches from the triggering run, evaluate event metadata as code, or infer merge/release authorization from a triage issue.

## Threat model

### Assets
Repository integrity, CI evidence integrity, issue tracker integrity, release/merge decisions, secrets and token authority.

### Actors
Repository maintainers; GitHub Actions control plane; contributors controlling PR branches and workflow metadata; compromised third-party action publisher; autonomous NEXUS workers/reviewers.

### Trust boundaries
1. Triggering workflow -> privileged `workflow_run` event.
2. GitHub event metadata -> issue body/title construction.
3. Third-party action code -> repository-scoped token.
4. Triage evidence -> downstream human/automation decisions.

## Abuse cases

- A malicious PR causes a failing run and injects crafted branch/workflow metadata.
- A non-allow-listed workflow or successful run attempts to create evidence.
- Duplicate event delivery creates issue spam or divergent evidence.
- A compromised mutable action tag gains `issues:write` authority.
- A future edit adds checkout/artifact execution and turns untrusted input into privileged code execution.
- Triage evidence is misread as merge/release approval.

## Deny-by-default policy

The workflow performs no write unless the source workflow is allow-listed and the conclusion is one of `failure`, `cancelled`, `timed_out`, or `action_required`. Missing/malformed fields, unknown workflow names, neutral/success/skipped conclusions, or ambiguous authority must result in no privileged side effect. The workflow may write only issue evidence; all release/merge/trading authority remains denied.

## Verification

Positive tests must prove allow-listed failure-like events are accepted and that repeated delivery maps to the same marker key. Negative tests must prove success/neutral/skipped/unknown workflow events are rejected. Bypass tests must prove the workflow contains no checkout, artifact execution, triggering-run cache consumption, shell interpolation of untrusted metadata, or mutable third-party action reference. Tests also assert the exact permission set and full-SHA pin.

## Rollback and recovery

Rollback by disabling/removing the workflow and reverting this ADR/policy tuple. Preserve already-created triage issues as historical evidence, but do not treat them as current authorization. Restore the previous-known-good workflow permissions policy, then re-run exact-head CI before re-enabling. If an abuse or false-positive incident occurs, quarantine newly created triage evidence until the root cause is identified.

## Obsolescence triggers

Re-review this ADR when GitHub changes `workflow_run`, `GITHUB_TOKEN`, repository ruleset, cache/artifact trust semantics, action pinning guidance, or when the pinned action is deprecated/advised vulnerable. Also re-review after any false-positive, privilege escalation, evidence spoofing, or recursion incident.

## Evidence triangulation

- Official standard: NIST SP 800-218 SSDF v1.1 recommends integrating secure development practices into the SDLC and addressing root causes of vulnerabilities.
- Independent research: Torres-Arias et al., *in-toto* (USENIX Security 2019), demonstrates the value of authenticated, explicitly bound software-supply-chain evidence.
- Implementation guidance: GitHub Secure Use guidance recommends least privilege and full-length commit SHA pinning for immutable third-party action references; GitHub documents that `workflow_run` can operate with elevated token/secrets relative to the triggering workflow.
- Incident evidence: Codecov's 2021 Bash Uploader compromise showed CI supply-chain code can exfiltrate environment variables and that checksum mismatch can reveal tampering.
- Limitation/opposing view: this design does not checkout untrusted code and limits write authority to issues, materially reducing exploitability. It still cannot eliminate GitHub control-plane compromise, malicious behavior inside the pinned action commit, or pre-merge proof of actual `workflow_run` delivery because a new workflow must exist on the default branch to receive such events.

## Residual risk

A compromised GitHub control plane or reviewed pinned action commit remains outside this control. Issue evidence is advisory telemetry only. A bounded post-merge canary is required to validate real event delivery; failure of that canary requires rollback or a new reviewed ADR revision, never gate weakening.
