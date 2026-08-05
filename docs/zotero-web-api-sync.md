# Zotero Web API Sync

This workflow uploads only validated CSL JSON metadata. It does not upload PDFs, private notes, local attachment paths, credentials, or Zotero database files.

## Required repository secrets

Add these in GitHub repository settings under **Settings → Secrets and variables → Actions**:

- `ZOTERO_API_KEY`: a Zotero API key with write access to the target personal library.
- `ZOTERO_LIBRARY_ID`: the numeric Zotero user/library ID.

Never commit either value to Git, issues, logs, screenshots, or documentation.

## Safe first run

1. Prepare `references/crypto-fx-library.json` as a CSL JSON array.
2. Open **Actions → Zotero Web API Sync → Run workflow**.
3. Keep `apply` disabled. This validates locally and performs no remote write.
4. Review the file and workflow result.
5. Enable `apply` only after the dry-run passes.
6. Optionally supply an existing Zotero collection key.

## Deny-by-default behavior

- Remote writes are disabled unless `apply=true`.
- Missing secrets fail closed.
- Empty input, unsupported item types, missing titles, and duplicate DOI/URL/title identities are rejected.
- The workflow has read-only GitHub repository permissions.
- Collection creation and deletion are intentionally out of scope for the first version.

## Rollback and recovery

Zotero item creation is not automatically reversed. Before a large upload, use a dedicated collection and test with a small batch. If a batch is incorrect, remove that batch from Zotero manually and correct the source JSON before retrying. Git history remains the authoritative versioned source metadata record.

## Supported CSL types

`article-journal`, `book`, `chapter`, `paper-conference`, `report`, `thesis`, and `webpage`.
