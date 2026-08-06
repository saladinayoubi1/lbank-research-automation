# Zotero Metadata Quality Report v2

## Safety boundary

`tools/zotero_metadata_audit.py` is read-only and offline. It reads one local Zotero JSON export and writes findings only to stdout/stderr. It has no Zotero API client, network request, credential input, delete, merge, metadata update, collection move, or sync-write path.

Malformed JSON and unsupported payload shapes fail closed with exit code `2` and no report.

## Usage

```bash
python tools/zotero_metadata_audit.py export.json --json
```

Exit codes:

- `0`: valid input and no findings;
- `1`: valid input with metadata or duplicate findings;
- `2`: unreadable, malformed, or structurally invalid input.

## Stable JSON schema

Top-level keys are emitted deterministically with `sort_keys=True`:

```json
{
  "duplicates": {
    "doi": [
      {"doi": "10.1000/example", "indexes": [0, 4]}
    ],
    "title_year": [
      {"indexes": [1, 3], "title": "normalized title", "year": "2024"}
    ]
  },
  "finding_count": 3,
  "item_count": 5,
  "items": [
    {
      "creator_findings": ["missing_creators"],
      "index": 2,
      "missing_fields": ["year", "DOI"],
      "title": "Original title"
    }
  ],
  "mode": "read-only-offline",
  "schema_version": "2.0"
}
```

### Field definitions

- `schema_version`: report contract version.
- `mode`: fixed safety declaration, `read-only-offline`.
- `item_count`: number of validated item objects in the export.
- `finding_count`: total missing-field and creator-quality findings plus duplicate candidate groups.
- `items`: input-indexed metadata findings.
- `missing_fields`: missing `title`, `year`, and DOI for article-like item types.
- `creator_findings`: sorted codes for missing or incomplete creator data.
- `duplicates.doi`: conservative groups sharing a normalized non-empty DOI.
- `duplicates.title_year`: conservative groups sharing normalized non-empty title and extracted year.

Duplicate entries are candidates only. The tool never merges, deletes, edits, or moves Zotero items.

## Determinism

- Unicode text is normalized with NFKC, case-folded, trimmed, and whitespace-collapsed.
- DOI prefixes are normalized before grouping.
- Duplicate groups and creator finding codes are sorted.
- Item indexes preserve export order.
- JSON keys are sorted and indentation is fixed.
- No timestamps, environment values, secrets, network data, or random identifiers enter the report.

## Rollback

Rollback is repository-only:

1. Close the draft PR without merging, or revert its commits after merge.
2. Restore `tools/zotero_metadata_audit.py` and `tests/test_zotero_metadata_audit.py` to the previous revision.
3. Remove this schema document if v2 is withdrawn.

No Zotero-side rollback is required because the tool cannot write to Zotero or alter the input export.
