from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

import pandas as pd

import bybit_spot_backfill as backfill
import stream_bybit_symbol_month as stream
from scripts.nexus_bybit_replay_chunks import CANONICAL_CHUNK_MAP


SYMBOLS = ("BTCUSDT", "ETHUSDT")


def _validate_chunk_request(chunk_id: str, start_date: str, end_date: str) -> None:
    expected = CANONICAL_CHUNK_MAP.get(chunk_id)
    if expected is None:
        raise SystemExit(f"Unknown replay chunk id: {chunk_id}")
    if (start_date, end_date) != (expected.start, expected.end):
        raise SystemExit(
            f"Chunk {chunk_id} date mismatch: got {start_date}..{end_date}, "
            f"expected {expected.start}..{expected.end}"
        )


def build_rehydrated_chunk(
    *,
    chunk_id: str,
    start_date: str,
    end_date: str,
    output_root: Path,
    cache_root: Path,
) -> dict:
    _validate_chunk_request(chunk_id, start_date, end_date)
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    parts_root = output_root.parent / f".{output_root.name}-parts"
    if parts_root.exists():
        shutil.rmtree(parts_root)
    parts_root.mkdir(parents=True, exist_ok=True)

    reports = []
    part_roots = []
    for symbol in SYMBOLS:
        part_root = parts_root / symbol
        symbol_cache = cache_root / symbol
        if symbol_cache.exists():
            shutil.rmtree(symbol_cache)
        report = stream.build_symbol_month(
            symbol,
            start_date,
            end_date,
            part_root,
            symbol_cache,
        )
        summary = report["summary"]
        if not (
            summary["backfill_complete"] is True
            and summary["completed_units"] == 1
            and summary["remaining_units"] == 0
            and summary["run_failures"] == 0
            and summary["current_dataset_integrity_ok"] is True
            and len(report["statuses"]) == 3
            and all(
                item["integrity_ok"] is True and item["status"] == "ready"
                for item in report["statuses"]
            )
        ):
            raise SystemExit(f"Streaming verification failed for {chunk_id} {symbol}")
        reports.append(report)
        part_roots.append(part_root)

    statuses = []
    sources = []
    runs = []
    completed_unit = None
    filenames: dict[str, str] = {}

    for part_root, report in zip(part_roots, reports):
        checkpoint = json.loads((part_root / "_checkpoint.json").read_text(encoding="utf-8"))
        manifest = json.loads((part_root / "_source_manifest.json").read_text(encoding="utf-8"))
        statuses.extend(report["statuses"])
        sources.extend(manifest)
        runs.extend(checkpoint.get("runs", []))
        unit = checkpoint["completed_units"][0]
        if completed_unit is None:
            completed_unit = dict(unit)
        elif completed_unit["unit_id"] != unit["unit_id"]:
            raise SystemExit(f"Mismatched completed units for chunk {chunk_id}")
        filenames.update({str(key): str(value) for key, value in unit.get("filenames", {}).items()})
        shutil.copytree(part_root / "bybit_market", output_root / "bybit_market", dirs_exist_ok=True)

    if completed_unit is None:
        raise SystemExit(f"No completed unit produced for chunk {chunk_id}")
    completed_unit["filenames"] = filenames

    if len(sources) != 2:
        raise SystemExit(f"Expected two official source archives for chunk {chunk_id}, found {len(sources)}")
    if len(statuses) != 6:
        raise SystemExit(f"Expected six ready series for chunk {chunk_id}, found {len(statuses)}")
    if not all(item["integrity_ok"] is True and item["status"] == "ready" for item in statuses):
        raise SystemExit(f"A rebuilt series is not ready for chunk {chunk_id}")

    checkpoint = {
        "schema_version": 1,
        "completed_units": [completed_unit],
        "failed_units": [],
        "runs": runs,
    }
    combined = {
        "generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "configuration": {
            "start_date": start_date,
            "end_date": end_date,
            "symbols": list(SYMBOLS),
            "max_archives_per_run": 2,
        },
        "summary": {
            "plan_units": 1,
            "plan_archives": 2,
            "completed_units": 1,
            "remaining_units": 0,
            "units_completed_this_run": 1,
            "archives_completed_this_run": 2,
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "completed_this_run": [completed_unit],
        "sources_this_run": sources,
        "run_failures": [],
        "statuses": statuses,
    }

    backfill.write_json(output_root / "_checkpoint.json", checkpoint)
    backfill.write_json(output_root / "_source_manifest.json", sources)
    backfill.write_json(output_root / "_backfill_report.json", combined)
    pd.DataFrame(sources).to_csv(output_root / "_source_manifest.csv", index=False)
    pd.DataFrame(statuses).to_csv(output_root / "_backfill_status.csv", index=False)
    shutil.rmtree(parts_root)
    print(json.dumps(combined["summary"], sort_keys=True))
    return combined


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-id", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_rehydrated_chunk(
        chunk_id=args.chunk_id,
        start_date=args.start_date,
        end_date=args.end_date,
        output_root=args.output_root,
        cache_root=args.cache_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
