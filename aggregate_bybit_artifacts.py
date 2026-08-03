from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

import bybit_spot_archive_audit as audit
import bybit_spot_archive_collector as collector

DEFAULT_START_DATE = "2022-12-01"
DEFAULT_END_DATE = "2026-07-31"
DEFAULT_INPUT_ROOT = Path("build/bybit_artifacts")
DEFAULT_OUTPUT_ROOT = Path("build/bybit_full_history")
DEFAULT_ZIP_PATH = Path("build/BYBIT_full_history_2022-12-01_to_2026-07-31.zip")
BASE_RANGE = ("2022-12-01", "2023-01-31")


class BybitArtifactAggregationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    root: Path
    start_date: str
    end_date: str
    generated_at_utc: str
    report: dict[str, Any]
    checkpoint: dict[str, Any]
    sources: list[dict[str, Any]]

    @property
    def range_key(self) -> tuple[str, str]:
        return self.start_date, self.end_date


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_month_ranges(start_date: str, end_date: str) -> list[tuple[str, str]]:
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        raise BybitArtifactAggregationError("end_date cannot be before start_date")
    ranges: list[tuple[str, str]] = []
    for period in pd.period_range(start, end, freq="M"):
        month_start = max(start, period.start_time.normalize())
        month_end = min(end, period.end_time.normalize())
        ranges.append(
            (month_start.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d"))
        )
    return ranges


def validate_snapshot(root: Path) -> Snapshot:
    report_path = root / "_backfill_report.json"
    checkpoint_path = root / "_checkpoint.json"
    sources_path = root / "_source_manifest.json"
    missing_metadata = [
        path.name
        for path in (report_path, checkpoint_path, sources_path)
        if not path.is_file()
    ]
    if missing_metadata:
        raise BybitArtifactAggregationError(
            f"Snapshot {root} is missing metadata: {missing_metadata}"
        )

    report = read_json(report_path)
    checkpoint = read_json(checkpoint_path)
    sources = read_json(sources_path)
    config = report.get("configuration", {})
    start_date = str(config.get("start_date", ""))
    end_date = str(config.get("end_date", ""))
    generated_at = str(report.get("generated_at_utc", ""))
    if not start_date or not end_date or not generated_at:
        raise BybitArtifactAggregationError(
            f"Snapshot {root} has incomplete report configuration"
        )

    summary = report.get("summary", {})
    statuses = report.get("statuses", [])
    run_failures = report.get("run_failures", [])
    if not bool(summary.get("backfill_complete")):
        raise BybitArtifactAggregationError(f"Snapshot {root} is incomplete")
    if not bool(summary.get("current_dataset_integrity_ok")):
        raise BybitArtifactAggregationError(
            f"Snapshot {root} failed dataset integrity"
        )
    if int(summary.get("remaining_units", -1)) != 0:
        raise BybitArtifactAggregationError(
            f"Snapshot {root} still has remaining units"
        )
    if int(summary.get("run_failures", len(run_failures))) != 0 or run_failures:
        raise BybitArtifactAggregationError(f"Snapshot {root} has run failures")
    if len(statuses) != len(audit.SYMBOLS) * len(audit.TIMEFRAME_RULES):
        raise BybitArtifactAggregationError(
            f"Snapshot {root} has {len(statuses)} statuses instead of 6"
        )
    if not all(
        bool(item.get("integrity_ok")) and item.get("status") == "ready"
        for item in statuses
    ):
        raise BybitArtifactAggregationError(
            f"Snapshot {root} contains a non-ready series"
        )
    if checkpoint.get("schema_version") != 1:
        raise BybitArtifactAggregationError(
            f"Snapshot {root} has an unsupported checkpoint schema"
        )
    if checkpoint.get("failed_units"):
        raise BybitArtifactAggregationError(
            f"Snapshot {root} checkpoint contains failed units"
        )
    if not isinstance(sources, list) or not sources:
        raise BybitArtifactAggregationError(
            f"Snapshot {root} has an empty source manifest"
        )

    for source_symbol in audit.SYMBOLS:
        canonical = collector.canonical_symbol(source_symbol)
        for timeframe in audit.TIMEFRAME_RULES:
            parquet_path = root / "bybit_market" / canonical / f"{timeframe}.parquet"
            if not parquet_path.is_file():
                raise BybitArtifactAggregationError(
                    f"Snapshot {root} is missing {parquet_path.relative_to(root)}"
                )

    return Snapshot(
        root=root,
        start_date=start_date,
        end_date=end_date,
        generated_at_utc=generated_at,
        report=report,
        checkpoint=checkpoint,
        sources=sources,
    )


def discover_valid_snapshots(input_root: Path) -> tuple[list[Snapshot], list[dict[str, str]]]:
    candidates: list[Snapshot] = []
    rejected: list[dict[str, str]] = []
    for report_path in sorted(input_root.rglob("_backfill_report.json")):
        root = report_path.parent
        try:
            candidates.append(validate_snapshot(root))
        except Exception as exc:
            rejected.append(
                {
                    "root": root.as_posix(),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return candidates, rejected


def select_required_snapshots(
    candidates: list[Snapshot],
    start_date: str,
    end_date: str,
) -> list[Snapshot]:
    by_range: dict[tuple[str, str], list[Snapshot]] = {}
    for candidate in candidates:
        by_range.setdefault(candidate.range_key, []).append(candidate)

    required_ranges = [BASE_RANGE]
    required_ranges.extend(
        item
        for item in expected_month_ranges("2023-02-01", end_date)
        if item[0] >= "2023-02-01"
    )
    if start_date != BASE_RANGE[0]:
        raise BybitArtifactAggregationError(
            f"This aggregator requires start_date {BASE_RANGE[0]}"
        )

    selected: list[Snapshot] = []
    missing: list[tuple[str, str]] = []
    for range_key in required_ranges:
        options = by_range.get(range_key, [])
        if not options:
            missing.append(range_key)
            continue
        selected.append(max(options, key=lambda item: item.generated_at_utc))
    if missing:
        raise BybitArtifactAggregationError(
            "Missing valid artifact ranges: "
            + ", ".join(f"{start}..{end}" for start, end in missing)
        )

    selected.sort(key=lambda item: item.start_date)
    cursor = pd.Timestamp(start_date)
    final_end = pd.Timestamp(end_date)
    for snapshot in selected:
        snapshot_start = pd.Timestamp(snapshot.start_date)
        snapshot_end = pd.Timestamp(snapshot.end_date)
        if snapshot_start != cursor:
            raise BybitArtifactAggregationError(
                f"Coverage discontinuity before {snapshot.start_date}; expected {cursor.date()}"
            )
        if snapshot_end < snapshot_start:
            raise BybitArtifactAggregationError(
                f"Invalid snapshot range: {snapshot.range_key}"
            )
        cursor = snapshot_end + pd.Timedelta(1, unit="D")
    if cursor != final_end + pd.Timedelta(1, unit="D"):
        raise BybitArtifactAggregationError(
            f"Coverage ends at {(cursor - pd.Timedelta(1, unit='D')).date()} instead of {end_date}"
        )
    return selected


def combine_checkpoint(selected: list[Snapshot]) -> dict[str, Any]:
    completed_by_id: dict[str, dict[str, Any]] = {}
    runs: list[dict[str, Any]] = []
    for snapshot in selected:
        for unit in snapshot.checkpoint.get("completed_units", []):
            completed_by_id[str(unit["unit_id"])] = unit
        runs.extend(snapshot.checkpoint.get("runs", []))
    completed = sorted(
        completed_by_id.values(),
        key=lambda unit: (str(unit.get("start_date", "")), str(unit.get("unit_id", ""))),
    )
    expected_units = len(expected_month_ranges(DEFAULT_START_DATE, DEFAULT_END_DATE))
    if len(completed) != expected_units:
        raise BybitArtifactAggregationError(
            f"Checkpoint has {len(completed)} completed units instead of {expected_units}"
        )
    return {
        "schema_version": 1,
        "completed_units": completed,
        "failed_units": [],
        "runs": runs,
    }


def combine_sources(selected: list[Snapshot]) -> list[dict[str, Any]]:
    source_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for snapshot in selected:
        for source in snapshot.sources:
            key = (str(source.get("symbol", "")), str(source.get("filename", "")))
            if not all(key):
                raise BybitArtifactAggregationError(
                    f"Source manifest entry lacks symbol or filename in {snapshot.root}"
                )
            existing = source_by_key.get(key)
            if existing and str(existing.get("sha256")) != str(source.get("sha256")):
                raise BybitArtifactAggregationError(
                    f"Conflicting source digest for {key[0]} {key[1]}"
                )
            source_by_key[key] = source
    sources = sorted(
        source_by_key.values(),
        key=lambda item: (
            str(item.get("start_date", "")),
            str(item.get("symbol", "")),
            str(item.get("filename", "")),
        ),
    )
    expected_archives = len(expected_month_ranges(DEFAULT_START_DATE, DEFAULT_END_DATE)) * len(
        audit.SYMBOLS
    )
    if len(sources) != expected_archives:
        raise BybitArtifactAggregationError(
            f"Source manifest has {len(sources)} archives instead of {expected_archives}"
        )
    return sources


def aggregate_series(
    selected: list[Snapshot],
    output_root: Path,
    start_date: str,
    end_date: str,
) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for source_symbol in audit.SYMBOLS:
        canonical = collector.canonical_symbol(source_symbol)
        destination = output_root / "bybit_market" / canonical
        destination.mkdir(parents=True, exist_ok=True)
        for timeframe in audit.TIMEFRAME_RULES:
            frames: list[pd.DataFrame] = []
            for snapshot in selected:
                parquet_path = (
                    snapshot.root
                    / "bybit_market"
                    / canonical
                    / f"{timeframe}.parquet"
                )
                frame = pd.read_parquet(parquet_path)
                missing_columns = sorted(
                    set(collector.CANONICAL_COLUMNS).difference(frame.columns)
                )
                if missing_columns:
                    raise BybitArtifactAggregationError(
                        f"{parquet_path} is missing columns {missing_columns}"
                    )
                frame = frame.loc[:, collector.CANONICAL_COLUMNS].copy()
                frame["timestamp"] = pd.to_datetime(
                    frame["timestamp"], utc=True, errors="raise"
                )
                range_start = pd.Timestamp(snapshot.start_date, tz="UTC")
                range_end = pd.Timestamp(snapshot.end_date, tz="UTC") + pd.Timedelta(
                    1, unit="D"
                )
                outside = ~frame["timestamp"].ge(range_start) | ~frame[
                    "timestamp"
                ].lt(range_end)
                if int(outside.sum()) != 0:
                    raise BybitArtifactAggregationError(
                        f"{parquet_path} contains {int(outside.sum())} out-of-range rows"
                    )
                frames.append(frame)

            combined = pd.concat(frames, ignore_index=True)
            normalized, status = collector.evaluate_series(
                combined,
                source_symbol,
                timeframe,
                start_date,
                end_date,
            )
            if not bool(status["integrity_ok"]) or status["status"] != "ready":
                raise BybitArtifactAggregationError(
                    f"Full-range integrity failed for {canonical}/{timeframe}: {status}"
                )
            normalized.to_parquet(
                destination / f"{timeframe}.parquet",
                index=False,
                compression="zstd",
            )
            statuses.append(status)
    return statuses


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Bybit Full History Snapshot",
        "",
        f"Generated at: {report['generated_at_utc']}",
        f"Range: {report['configuration']['start_date']} through {report['configuration']['end_date']} UTC",
        "",
        "## Summary",
        "",
        f"- Full history ready: **{report['summary']['full_history_ready']}**",
        f"- Selected snapshot inputs: {report['summary']['selected_snapshot_inputs']}",
        f"- Completed monthly units: {report['summary']['completed_units']}",
        f"- Source archives: {report['summary']['source_archives']}",
        f"- Malformed CSV rows audited and skipped: {report['summary']['malformed_csv_rows']}",
        "",
        "| Symbol | Timeframe | Rows | Expected | Missing | Gaps | Duplicates | Off-grid | Invalid OHLC | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["statuses"]:
        lines.append(
            "| {symbol} | {timeframe} | {rows} | {expected_rows} | {missing_candles} | {gap_count} | {duplicate_count} | {off_grid_count} | {invalid_ohlc_count} | {status} |".format(
                **item
            )
        )
    lines.append("")
    return "\n".join(lines)


def build_inventory(output_root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    excluded = {"_snapshot_manifest.json", "SHA256SUMS.txt"}
    for path in sorted(output_root.rglob("*")):
        if not path.is_file() or path.name in excluded:
            continue
        record: dict[str, Any] = {
            "path": path.relative_to(output_root).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        if path.suffix == ".parquet":
            frame = pd.read_parquet(path)
            timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
            record.update(
                {
                    "rows": int(len(frame)),
                    "first_candle_utc": timestamps.min().isoformat(),
                    "last_candle_utc": timestamps.max().isoformat(),
                    "columns": list(frame.columns),
                }
            )
        inventory.append(record)
    return inventory


def write_sha256s(output_root: Path) -> None:
    paths = [
        path
        for path in sorted(output_root.rglob("*"))
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    lines = [
        f"{sha256_file(path)}  {path.relative_to(output_root).as_posix()}"
        for path in paths
    ]
    (output_root / "SHA256SUMS.txt").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def aggregate_artifacts(
    input_root: Path = DEFAULT_INPUT_ROOT,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    zip_path: Path = DEFAULT_ZIP_PATH,
    start_date: str = DEFAULT_START_DATE,
    end_date: str = DEFAULT_END_DATE,
    clean: bool = False,
) -> dict[str, Any]:
    if clean and output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    candidates, rejected = discover_valid_snapshots(input_root)
    selected = select_required_snapshots(candidates, start_date, end_date)
    checkpoint = combine_checkpoint(selected)
    sources = combine_sources(selected)
    statuses = aggregate_series(selected, output_root, start_date, end_date)

    status_frame = pd.DataFrame(statuses)
    malformed_rows = sum(int(item.get("malformed_csv_rows", 0)) for item in sources)
    skipped_rows = sum(int(item.get("source_rows_skipped", 0)) for item in sources)
    full_history_ready = (
        len(statuses) == len(audit.SYMBOLS) * len(audit.TIMEFRAME_RULES)
        and bool(status_frame["integrity_ok"].all())
        and status_frame["status"].eq("ready").all()
        and len(checkpoint["completed_units"])
        == len(expected_month_ranges(start_date, end_date))
        and len(sources)
        == len(expected_month_ranges(start_date, end_date)) * len(audit.SYMBOLS)
    )
    if not full_history_ready:
        raise BybitArtifactAggregationError("Final full-history readiness gate failed")

    report = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "venue": "bybit",
        "market": "spot",
        "source": "official_public_spot_trade_archive",
        "configuration": {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": list(audit.SYMBOLS),
            "timeframes": list(audit.TIMEFRAME_RULES),
        },
        "summary": {
            "full_history_ready": True,
            "selected_snapshot_inputs": len(selected),
            "completed_units": len(checkpoint["completed_units"]),
            "source_archives": len(sources),
            "ready_series": int(status_frame["integrity_ok"].sum()),
            "malformed_csv_rows": malformed_rows,
            "source_rows_skipped": skipped_rows,
            "rejected_artifact_candidates": len(rejected),
        },
        "selected_inputs": [
            {
                "root": item.root.as_posix(),
                "start_date": item.start_date,
                "end_date": item.end_date,
                "generated_at_utc": item.generated_at_utc,
                "report_sha256": sha256_file(item.root / "_backfill_report.json"),
            }
            for item in selected
        ],
        "rejected_inputs": rejected,
        "statuses": statuses,
    }

    write_json(output_root / "_checkpoint.json", checkpoint)
    write_json(output_root / "_source_manifest.json", sources)
    pd.DataFrame(sources).to_csv(output_root / "_source_manifest.csv", index=False)
    status_frame.to_csv(output_root / "_backfill_status.csv", index=False)
    write_json(output_root / "_backfill_report.json", report)
    (output_root / "_backfill_report.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    inventory = build_inventory(output_root)
    write_json(output_root / "_snapshot_manifest.json", inventory)
    write_sha256s(output_root)

    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    archive_base = zip_path.with_suffix("")
    created = Path(
        shutil.make_archive(
            archive_base.as_posix(),
            "zip",
            root_dir=output_root,
        )
    )
    if created != zip_path:
        created.replace(zip_path)
    report["snapshot_zip"] = {
        "path": zip_path.as_posix(),
        "size_bytes": zip_path.stat().st_size,
        "sha256": sha256_file(zip_path),
    }
    write_json(output_root / "_backfill_report.json", report)
    (output_root / "_backfill_report.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    write_json(output_root / "_snapshot_manifest.json", build_inventory(output_root))
    write_sha256s(output_root)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggregate independently verified Bybit monthly artifacts into one strict full-history snapshot."
    )
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--zip-path", type=Path, default=DEFAULT_ZIP_PATH)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--clean", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = aggregate_artifacts(
        input_root=args.input_root,
        output_root=args.output_root,
        zip_path=args.zip_path,
        start_date=args.start_date,
        end_date=args.end_date,
        clean=args.clean,
    )
    print(json.dumps(report["summary"], sort_keys=True))
    print(json.dumps(report["snapshot_zip"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
