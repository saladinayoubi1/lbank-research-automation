# ADR-026 — Project Memory Drive Backup Verification

Status: Accepted for Research/Backtest/Paper continuity controls. Issue: #122.

## Decision

The repository remains the durable source of truth. Google Drive is a secondary continuity copy only, and a Drive object is not a valid recovery candidate merely because it exists. A candidate becomes eligible only when a fail-closed verifier binds one exact repository snapshot to one exact Drive object revision and verifies the backed-up bytes.

The canonical backup document is UTF-8 JSON using `nexus.project-memory-backup-document.v1`. It contains the exact source repository, exact 40-hex source SHA, generation time, and a bounded mapping of canonical Project Memory file paths to their complete text. The companion manifest uses `nexus.project-memory-backup-manifest.v1` and binds:

- repository and exact source SHA;
- Drive object ID, revision ID, expected name, provider modified time;
- SHA-256 and byte length of the exported document text;
- each embedded source path, byte length and SHA-256;
- aggregate digest of the ordered source-file records;
- deterministic privacy-policy version, scanned byte count and findings.

A consumer must pass the current expected object/revision/name and expected source SHA to the verifier. Missing, stale, future, substituted, malformed, hash-mismatched, privacy-unsafe or unverifiable candidates are quarantined. Validation never mutates previous-valid state. Promotion to `previous-valid` occurs atomically only after all checks pass.

## Assets and trust boundaries

`repository Project Memory -> snapshot builder -> Google Drive document revision -> manifest/evidence -> verifier -> previous-valid recovery candidate`

Assets are Project Memory file contents, exact repository identity/SHA, Drive object/revision identity, manifest digests, previous-valid metadata and privacy boundary. GitHub and Google Drive are separate evidence domains; neither provider's mutable filename or existence assertion is sufficient by itself.

## Threat / abuse model

The verifier must fail closed on:

| Threat | Required denial |
| --- | --- |
| stale/replayed backup | generation age outside bounded freshness or wrong revision |
| future timestamp | generation/provider time beyond allowed clock skew |
| wrong repository/SHA | exact equality required |
| Drive substitution | exact object ID, revision ID and document name required |
| content substitution | exported document SHA-256 and size mismatch |
| plausible but poisoned manifest | source records recomputed from embedded snapshot and compared exactly |
| path escape/alias | absolute, `..`, backslash and noncanonical paths rejected |
| unknown schema/field smuggling | exact schema and exact field sets required |
| secret leakage | actual document and embedded source text scanned; stored boolean alone is never trusted |
| private chat transcript backup | private transcript markers are rejected |
| failed candidate overwriting good recovery state | validate first; atomic replace only after success |
| production-authority smuggling | backup metadata grants no signing, billing, deployment, credential or Live/L4 authority |

## Privacy scope

Backups may contain only repository Project Memory material selected for continuity. They must not contain private chat transcripts, memory dumps, credentials, tokens, private keys or password/API-key assignments. The verifier scans actual exported document text and every embedded source file; `contains_secrets=false` or equivalent assertions do not establish safety.

The scanner is deliberately conservative and bounded. It is a continuity/privacy gate, not a general DLP or security certification. New credential formats or transcript formats are obsolescence triggers.

## Evidence hierarchy

1. Exact repository bytes at a fixed source SHA.
2. Exact Drive object revision exported as text.
3. Content-bound manifest recomputed against those bytes.
4. Verifier result and immutable digest tuple.
5. Previous-valid recovery record promoted only after successful verification.

Chat history and a Drive object's mere existence are not authoritative recovery evidence.

## Recovery and rollback

A recovery exercise must include one valid candidate and adversarial stale/replayed/substituted/poisoned candidates. Invalid candidates are quarantined and previous-valid bytes remain unchanged. The valid candidate may atomically replace previous-valid only after exact binding succeeds. Recovery from Drive never widens system authority and cannot authorize production, signing, billing, private credentials or Live trading.

## Freshness

Default manifest freshness is 24 hours with at most five minutes of future clock skew. Operators may choose a tighter bound. Relaxing the bound requires an explicit policy change and corresponding tests; availability pressure must not silently weaken validation.

## Obsolescence triggers

Re-review this ADR after changes to Drive provider semantics, revision IDs, export format, Project Memory schema/layout, credential/token formats, privacy requirements, repository identity, hash algorithm, clock/freshness policy, or after any false-green, replay, backup corruption, substitution or recovery incident.

## Verification

`project_memory_backup.py` implements the bounded verifier and atomic previous-valid promotion. `tests/test_project_memory_backup_verifier.py` covers positive validation plus schema, freshness, source-SHA, object/revision/name substitution, content/hash poisoning, path escape, secret/private-transcript rejection, and previous-valid preservation.

## Authority boundary

This ADR changes continuity verification only. Research/Backtest/Paper remains the maximum authority. It creates no production-ready, DR-ready, signing, deployment, billing, exchange-credential or Live/L4 claim.
