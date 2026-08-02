from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

DEFAULT_DATA_ROOT = Path("data/market")
EXPECTED_PARQUET_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "symbol",
    "timeframe",
]


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_file_record(
    path: Path,
    data_root: Path,
    frame: pd.DataFrame,
) -> dict[str, Any]:
    schema_columns = frame.columns.tolist()
    row_count = int(len(frame))

    first_timestamp: str | None = None
    last_timestamp: str | None = None
    if row_count:
        normalized = pd.to_datetime(frame["timestamp"], utc=True)
        first_timestamp = pd.Timestamp(normalized.min()).isoformat()
        last_timestamp = pd.Timestamp(normalized.max()).isoformat()

    return {
        "path": path.relative_to(data_root).as_posix(),
        "symbol": path.parent.name,
        "timeframe": path.stem,
        "rows": row_count,
        "bytes": int(path.stat().st_size),
        "sha256": sha256_file(path),
        "first_candle_utc": first_timestamp,
        "last_candle_utc": last_timestamp,
        "columns": schema_columns,
        "schema_ok": schema_columns == EXPECTED_PARQUET_COLUMNS,
    }


def inspect_parquet(path: Path, data_root: Path) -> dict[str, Any]:
    frame = pd.read_parquet(path)
    return build_file_record(path, data_root, frame)


def build_snapshot_manifest(data_root: Path = DEFAULT_DATA_ROOT) -> dict[str, Any]:
    files = [
        inspect_parquet(path, data_root)
        for path in sorted(data_root.glob("*/*.parquet"))
    ]
    return {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source_commit": os.getenv("GITHUB_SHA"),
        "file_count": len(files),
        "total_rows": sum(item["rows"] for item in files),
        "total_bytes": sum(item["bytes"] for item in files),
        "all_schemas_ok": all(item["schema_ok"] for item in files),
        "files": files,
    }


def write_snapshot_manifest(
    data_root: Path = DEFAULT_DATA_ROOT,
) -> dict[str, Any]:
    data_root.mkdir(parents=True, exist_ok=True)
    manifest = build_snapshot_manifest(data_root)

    json_path = data_root / "_snapshot_manifest.json"
    md_path = data_root / "_snapshot_manifest.md"

    json_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# LBank Dataset Snapshot Manifest",
        "",
        f"- Generated at UTC: {manifest['generated_at_utc']}",
        f"- Source commit: {manifest['source_commit']}",
        f"- Parquet files: {manifest['file_count']}",
        f"- Total rows: {manifest['total_rows']}",
        f"- Total bytes: {manifest['total_bytes']}",
        f"- All schemas valid: {manifest['all_schemas_ok']}",
        "",
        "| Path | Rows | Bytes | First candle UTC | Last candle UTC | Schema OK | SHA-256 |",
        "|---|---:|---:|---|---|---|---|",
    ]
    for item in manifest["files"]:
        lines.append(
            "| {path} | {rows} | {bytes} | {first_candle_utc} | "
            "{last_candle_utc} | {schema_ok} | `{sha256}` |".format(**item)
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    manifest = write_snapshot_manifest()
    print(
        json.dumps(
            {
                "file_count": manifest["file_count"],
                "total_rows": manifest["total_rows"],
                "total_bytes": manifest["total_bytes"],
                "all_schemas_ok": manifest["all_schemas_ok"],
            },
            sort_keys=True,
        )
    )
    return 0 if manifest["all_schemas_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
