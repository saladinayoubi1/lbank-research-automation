# Dataset archive workflow

`Export dataset snapshot` packages the current `data/market` tree as a short-lived GitHub Actions artifact.

The export is intentionally manual after the initial pull-request validation. It does not contain Google Drive credentials and does not upload to external storage by itself. An authorized operator downloads the artifact, verifies the included `_snapshot_manifest.json`, and stores the archive in the project Drive.

The snapshot contains:

- all market-data Parquet files;
- `_backfill_status.csv` and `_backfill_status.md`;
- data-readiness reports when present;
- `_snapshot_manifest.json` and `_snapshot_manifest.md`;
- `_source_revision.txt` identifying the GitHub Actions checkout revision.

Artifact retention is limited to three days. Parquet files remain unchanged.
