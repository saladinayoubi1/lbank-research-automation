from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from main import COLUMNS, TIMEFRAME_SECONDS, analyze_timestamp_integrity

CANONICAL_COLUMNS = COLUMNS + ["symbol", "timeframe"]
MANIFEST_VERSION = 1


class PartitionError(RuntimeError):
    pass


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _load_source_metadata(input_root: Path) -> dict[str, Any]:
    manifest_path = input_root / "_snapshot_manifest.json"
    if not manifest_path.exists():
        return {
            "snapshot_manifest_path": None,
            "snapshot_manifest_sha256": None,
            "source_commit": None,
        }

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "snapshot_manifest_path": manifest_path.name,
        "snapshot_manifest_sha256": sha256_file(manifest_path),
        "source_commit": payload.get("source_commit"),
    }


def _read_and_validate_source(source_path: Path) -> tuple[pd.DataFrame, str, str]:
    frame = pd.read_parquet(source_path)
    actual_columns = list(frame.columns)
    if actual_columns != CANONICAL_COLUMNS:
        raise PartitionError(
            f"Schema mismatch in {source_path}: expected {CANONICAL_COLUMNS}, "
            f"got {actual_columns}"
        )

    symbol = source_path.parent.name
    timeframe = source_path.stem
    if timeframe not in TIMEFRAME_SECONDS:
        raise PartitionError(f"Unsupported timeframe in path: {source_path}")

    if not frame.empty:
        symbol_values = set(frame["symbol"].dropna().astype(str).unique())
        timeframe_values = set(frame["timeframe"].dropna().astype(str).unique())
        if symbol_values != {symbol}:
            raise PartitionError(
                f"Symbol identity mismatch in {source_path}: {sorted(symbol_values)}"
            )
        if timeframe_values != {timeframe}:
            raise PartitionError(
                f"Timeframe identity mismatch in {source_path}: "
                f"{sorted(timeframe_values)}"
            )

    normalized = frame.copy()
    try:
        normalized["timestamp"] = pd.to_datetime(
            normalized["timestamp"], utc=True, errors="raise"
        )
    except (TypeError, ValueError) as exc:
        raise PartitionError(f"Invalid timestamp in {source_path}") from exc

    normalized = normalized.sort_values("timestamp", kind="mergesort").reset_index(
        drop=True
    )
    return normalized, symbol, timeframe


def _partition_path(
    output_root: Path,
    symbol: str,
    timeframe: str,
    year: int,
    month: int,
) -> Path:
    return (
        output_root
        / f"symbol={symbol}"
        / f"timeframe={timeframe}"
        / f"year={year:04d}"
        / f"month={month:02d}"
        / "part-00000.parquet"
    )


def _render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# LBank Partitioned Dataset Manifest",
        "",
        f"Generated at UTC: {manifest['generated_at_utc']}",
        f"Source commit: {manifest.get('source_commit') or 'unknown'}",
        f"Source files: {manifest['source_file_count']}",
        f"Partitions: {manifest['partition_count']}",
        f"Total rows: {manifest['total_rows']}",
        f"All schemas valid: {manifest['all_schemas_ok']}",
        f"Row conservation valid: {manifest['row_conservation_ok']}",
        "",
        "| Symbol | Timeframe | Rows | Partitions | Missing candles | Gaps | Duplicates | Off-grid | Integrity OK |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]

    for item in manifest["source_files"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {partition_count} | "
            "{missing_candles} | {gap_count} | {duplicate_count} | "
            "{off_grid_count} | {integrity_ok} |".format(**item)
        )

    return "\n".join(lines) + "\n"


def build_partitioned_dataset(
    input_root: Path,
    output_root: Path,
    *,
    clean: bool = False,
) -> dict[str, Any]:
    input_root = Path(input_root)
    output_root = Path(output_root)

    source_paths = sorted(input_root.glob("*/*.parquet"))
    if not source_paths:
        raise PartitionError(f"No source Parquet files found under {input_root}")

    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    source_records: list[dict[str, Any]] = []
    partition_records: list[dict[str, Any]] = []
    source_row_total = 0
    partition_row_total = 0

    for source_path in source_paths:
        frame, symbol, timeframe = _read_and_validate_source(source_path)
        integrity = analyze_timestamp_integrity(frame["timestamp"], timeframe)
        source_row_total += len(frame)
        source_partition_count = 0

        if not frame.empty:
            working = frame.copy()
            working["_year"] = working["timestamp"].dt.year
            working["_month"] = working["timestamp"].dt.month

            for (year, month), partition in working.groupby(
                ["_year", "_month"], sort=True
            ):
                output_path = _partition_path(
                    output_root,
                    symbol,
                    timeframe,
                    int(year),
                    int(month),
                )
                output_path.parent.mkdir(parents=True, exist_ok=True)
                canonical_partition = partition[CANONICAL_COLUMNS].reset_index(drop=True)
                canonical_partition.to_parquet(
                    output_path,
                    index=False,
                    compression="zstd",
                )

                rows = len(canonical_partition)
                source_partition_count += 1
                partition_row_total += rows
                partition_records.append(
                    {
                        "path": output_path.relative_to(output_root).as_posix(),
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "year": int(year),
                        "month": int(month),
                        "rows": rows,
                        "first_candle_utc": canonical_partition[
                            "timestamp"
                        ].min().isoformat(),
                        "last_candle_utc": canonical_partition[
                            "timestamp"
                        ].max().isoformat(),
                        "bytes": output_path.stat().st_size,
                        "sha256": sha256_file(output_path),
                    }
                )

        source_records.append(
            {
                "path": source_path.relative_to(input_root).as_posix(),
                "symbol": symbol,
                "timeframe": timeframe,
                "rows": len(frame),
                "bytes": source_path.stat().st_size,
                "sha256": sha256_file(source_path),
                "partition_count": source_partition_count,
                **integrity,
            }
        )

    metadata = _load_source_metadata(input_root)
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "input_root": input_root.as_posix(),
        "output_root": output_root.as_posix(),
        **metadata,
        "source_file_count": len(source_records),
        "partition_count": len(partition_records),
        "total_rows": source_row_total,
        "partition_rows": partition_row_total,
        "row_conservation_ok": source_row_total == partition_row_total,
        "all_schemas_ok": True,
        "source_files": source_records,
        "partitions": partition_records,
    }

    if not manifest["row_conservation_ok"]:
        raise PartitionError(
            "Partition row count does not match source row count: "
            f"{partition_row_total} != {source_row_total}"
        )

    (output_root / "_partition_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_root / "_partition_manifest.md").write_text(
        _render_markdown(manifest),
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create a lossless year/month-partitioned research dataset."
    )
    parser.add_argument(
        "--input-root",
        type=Path,
        default=Path("data/market"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("build/partitioned_market"),
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the output directory before writing partitions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = build_partitioned_dataset(
        args.input_root,
        args.output_root,
        clean=args.clean,
    )
    print(
        "Partitioned "
        f"{manifest['source_file_count']} source files into "
        f"{manifest['partition_count']} partitions with "
        f"{manifest['total_rows']} rows."
    )


if __name__ == "__main__":
    main()
