# ADR-0010: Bound and quote Zotero workflow inputs

- Status: Proposed
- Version: 1.0.0
- Date: 2026-08-05
- Decision owner: NEXUS security governance
- Supersedes: unsafe interpolation in PR #46 workflow

## Context and threat model

The manually dispatched Zotero workflow accepts `input_file` and `collection_key`. The original workflow interpolated `collection_key` directly into a shell command and allowed any repository-relative input path. A repository administrator or compromised privileged session could therefore supply shell metacharacters or select an unintended JSON file while Zotero write credentials are present.

Assets: Zotero API key, target library integrity, evidence metadata, GitHub runner integrity, audit trail.

Trust boundaries: workflow-dispatch UI → GitHub expression engine → runner environment → shell → Python client → Zotero API.

Adversaries: compromised maintainer session, mistaken operator, malicious copied input, future workflow caller with dispatch permission.

## Evidence triangulation

1. Official standard: NIST SP 800-53 Rev. 5 SI-10 requires input validation; AC-6 requires least privilege. GitHub Actions security guidance warns against interpolating untrusted input directly into shell scripts and recommends intermediate environment variables.
2. Independent academic evidence: shell-command injection research consistently shows that quoting and structured argument passing are stronger than blacklist filtering; the control therefore uses an argument array plus a strict allowlist.
3. Implementation/incident evidence: CI/CD command-injection incidents commonly arise when event or dispatch fields are expanded in `run:` blocks with secret-bearing jobs. The prior workflow contained this exact primitive.
4. Limitation/opposing view: workflow dispatch is restricted to privileged repository users, so exploitability requires privilege or session compromise. That reduces likelihood but not impact; privileged interfaces remain in scope because secrets and external writes are reachable.

## Decision

- Put dispatch inputs into environment variables instead of direct expression interpolation in shell command text.
- Build the Python command with a Bash argument array.
- Restrict input files to resolved `.json` paths below `references/`.
- Restrict collection keys to 1-32 uppercase ASCII letters or digits.
- Require numeric Zotero library IDs.
- Preserve deny-by-default behavior: no remote write without explicit `apply=true` and valid secrets.

## Abuse cases and bypass tests

- `collection_key=ABC;id` → rejected.
- `collection_key=$(curl attacker)` → rejected.
- `input_file=references/../secrets.json` → rejected after path resolution.
- `input_file=references/items.txt` → rejected.
- Valid `references/items.json` and `ABC123` → accepted.

## Rollback and recovery

Rollback: revert this ADR and the associated workflow/script commit only if Zotero changes its collection-key format or repository layout. Recovery from a failed dispatch requires no secret rotation unless logs show secret disclosure. If a remote batch was written incorrectly, delete the isolated Zotero batch manually, repair source JSON, run dry-run, then reapply.

## Obsolescence triggers

Review when GitHub changes workflow input handling, Zotero changes key or API formats, the workflow becomes callable by untrusted events, attachments are added, OIDC replaces static API keys, or repository layout moves approved inputs outside `references/`.

## Verification

- Positive unit tests for valid path and key.
- Negative tests for traversal, extension bypass, lowercase/whitespace/metacharacter keys.
- Existing dry-run and missing-secret fail-closed tests remain required.
- No merge until CI is green and review threads are resolved.

## References

- NIST SP 800-53 Rev. 5, controls SI-10 and AC-6.
- GitHub Docs, Security hardening for GitHub Actions: script injection mitigations.
- OWASP Command Injection Defense Cheat Sheet.
- Zotero Web API v3 write-request documentation.
