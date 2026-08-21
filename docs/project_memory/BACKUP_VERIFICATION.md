# Project Memory Drive Backup Verification

Issue: #122. Architecture: `docs/architecture/ADR-026-project-memory-drive-backup-verification.md`.

## Authority

The repository is the durable source of truth. Google Drive is secondary continuity storage. No Drive object, filename, timestamp, boolean assertion or chat transcript can authorize recovery by itself.

Current continuity object:

- folder: `NEXUS Project Memory Backup`
- folder ID: `1BQa7YrH-1mc5Fsg3C_o-RdhiUmq2LoNJ`
- document: `NEXUS Project Memory Backup — Durable`
- document ID: `14wBdcjec0_0PhDzupk7QjaPlB3A_uw4A1EUzseeKQ4s`

The current object must be treated as unverified until an exact revision is exported and a manifest produced by `project_memory_backup.py` passes against the expected repository SHA and provider identity.

## Canonical backup set

A continuity snapshot should contain these repository-controlled files unless a later ADR changes the set:

- `docs/project_memory/PROJECT_MEMORY.md`
- `docs/project_memory/STATE.json`
- `docs/project_memory/DECISIONS.md`
- `docs/project_memory/RECOVERY_PLAYBOOK.md`
- `docs/project_memory/AUTONOMY_POLICY.md`
- `docs/project_memory/OPERATING_RULES.md`
- `docs/project_memory/VALIDATION.md`

The canonical Google Doc body is JSON using `nexus.project-memory-backup-document.v1`; it embeds the complete text of the selected files, repository identity, exact source SHA and generation time. Private chat transcripts and secrets are forbidden.

## Produce and verify

1. Read the exact selected files from one fixed repository SHA.
2. Build a canonical snapshot with `build_snapshot()` and `snapshot_text()`.
3. Replace the Drive document body with that snapshot only.
4. Re-read the Drive document and obtain its current revision ID and modified time.
5. Build the companion manifest with the exact re-read document text and provider metadata.
6. Run `validate_manifest()` using the expected repository, source SHA, object ID, revision ID and document name.
7. Persist only the verified digest tuple as repository evidence. Do not store credentials or private transcript material.
8. Exercise invalid stale/replay/substitution candidates and prove the previous-valid record is unchanged.

## Fail-closed reasons

Unknown/missing schema fields, stale/future timestamps, repository/SHA mismatch, object/revision/name substitution, content hash or size mismatch, source-file binding mismatch, noncanonical paths, secret-like material, private transcript markers and privacy scan inconsistencies all quarantine the candidate.

## Recovery

A recovery consumer must independently fetch the expected Drive revision, validate it under the current verifier/policy, and only then promote it to previous-valid. Failed candidates never overwrite previous-valid state. The repository remains authoritative when valid repository evidence is available.

## Claim boundary

Successful #122 verification establishes a content-bound secondary Project Memory recovery candidate. It does **not** establish general disaster-recovery readiness, production release readiness, signing/provenance authority, credentials authority, billing authority, deployment authority or Live/L4 trading authority. Those production claims remain governed by their separate open gates.
