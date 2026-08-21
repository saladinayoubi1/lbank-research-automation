# Project Memory Drive Backup Verification

Issue: #122. Architecture: `docs/architecture/ADR-026-project-memory-drive-backup-verification.md`.

## Authority

The repository is the durable source of truth. Google Drive is secondary continuity storage. No Drive object, filename, timestamp, boolean assertion or chat transcript can authorize recovery by itself.

Current continuity storage is the folder `NEXUS Project Memory Backup`. The recovery candidate must be identified by the exact object ID and exact Drive revision recorded in verified evidence; a filename alone is never identity.

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
3. Store that snapshot in a dedicated Google Docs object inside the backup folder; preserve any prior object as legacy/previous evidence rather than overwriting it before verification.
4. Re-read the exact Drive revision as `text/plain` and record provider object ID, revision ID and modified time.
5. Google Docs `text/plain` export may add one UTF-8 BOM and CRLF transport whitespace. Use `project_memory_drive_export.py`: raw provider text remains authoritative for SHA-256/size/privacy binding, while only the single leading BOM is removed for JSON interpretation. CRLF is not normalized out of the raw digest.
6. Build the companion manifest with `build_drive_export_manifest()` using the exact re-read raw provider text and provider metadata.
7. Run `validate_drive_export_manifest()` using the expected repository, source SHA, object ID, revision ID and document name.
8. Persist only the verified digest tuple as repository evidence. Do not store credentials or private transcript material.
9. Exercise invalid stale/replay/substitution/hash candidates and prove the previous-valid record is unchanged before promoting the verified candidate.

## Fail-closed reasons

Unknown/missing schema fields, stale/future timestamps, repository/SHA mismatch, object/revision/name substitution, raw provider content hash or size mismatch, source-file binding mismatch, noncanonical paths, secret-like material, private transcript markers and privacy scan inconsistencies all quarantine the candidate. A BOM is tolerated only as the single transport prefix emitted by the Google Docs text export; it is still included in the raw provider digest and size.

## Recovery

A recovery consumer must independently fetch the recorded Drive revision, validate its raw exported bytes under the current verifier/policy, and only then promote it to previous-valid. Failed candidates never overwrite previous-valid state. The repository remains authoritative when valid repository evidence is available.

## Claim boundary

Successful #122 verification establishes a content-bound secondary Project Memory recovery candidate. It does **not** establish general disaster-recovery readiness, production release readiness, signing/provenance authority, credentials authority, billing authority, deployment authority or Live/L4 trading authority. Those production claims remain governed by their separate gates.
