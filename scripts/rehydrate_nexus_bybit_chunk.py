from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd

import bybit_spot_backfill as backfill
import stream_bybit_symbol_month as stream
from scripts.nexus_bybit_replay_chunks import CANONICAL_CHUNK_MAP


SYMBOLS = ("BTCUSDT", "ETHUSDT")

# Raw archive identities from the verified canonical delivery, run 34677523584.
# These two months used the full-frame parser before streaming rehydration.
FROZEN_BULK_SOURCE_SHA256 = {
    "BTCUSDT-2024-04.csv.gz": "8cb31afd2c0b9472af44f398989ac761fe6daeecabb818df5ea39e6ac20114d6",
    "ETHUSDT-2024-04.csv.gz": "40f410fc166323356117923e9d1f46edef00ac0f040d0debcf8f0561c8dac611",
    "BTCUSDT-2024-05.csv.gz": "9cbaa94227511aa1724931c2ac226bff93ff8a15b740c476492a0a62a286a974",
    "ETHUSDT-2024-05.csv.gz": "eb84c6ad668a44574a1d6bfa73583d894fe9293d5fd8ca46b45af8d080cd7b33",
}


class FrozenReplaySemanticsError(RuntimeError):
    pass


def verify_frozen_bulk_sources(sources: list[dict]) -> list[dict]:
    """Require the exact four unchanged official archives before restoring candles."""
    if not isinstance(sources, list) or any(not isinstance(item, dict) for item in sources):
        raise FrozenReplaySemanticsError("invalid frozen bulk source manifest")
    found = {}
    for item in sources:
        filename = item.get("filename")
        if filename not in FROZEN_BULK_SOURCE_SHA256:
            continue
        if filename in found:
            raise FrozenReplaySemanticsError("duplicate frozen bulk source archive")
        symbol, year, month_file = filename.split("-")
        period = pd.Period(f"{year}-{month_file[:2]}", freq="M")
        expected = {
            "symbol": symbol,
            "start_date": period.start_time.strftime("%Y-%m-%d"),
            "end_date": period.end_time.strftime("%Y-%m-%d"),
            "url": f"https://public.bybit.com/spot/{symbol}/{filename}",
            "sha256": FROZEN_BULK_SOURCE_SHA256[filename],
        }
        if any(item.get(key) != value for key, value in expected.items()):
            raise FrozenReplaySemanticsError("frozen bulk raw archive identity mismatch")
        if item.get("parser_engine") != "c-chunked":
            raise FrozenReplaySemanticsError("unexpected frozen bulk parser provenance")
        found[filename] = {"filename": filename, **expected}
    if set(found) != set(FROZEN_BULK_SOURCE_SHA256):
        raise FrozenReplaySemanticsError("missing frozen bulk source archive")
    return [found[name] for name in sorted(found)]


def restore_frozen_bulk_semantics(output_root: Path, reference_root: Path) -> dict:
    """Preserve reviewed candle semantics without changing the frozen dataset pin.

    Bulk and chunked sorting can choose different first/last trades sharing a
    timestamp; chunked sums can also differ by one float ULP. Only the two
    historically bulk-parsed months may come from the verified frozen snapshot.
    Every other candle must already match, and all replacements are validated
    before any output file changes.
    """
    from nexus_demo_archive_contract import ARCHIVE_SHA256
    from scripts.build_nexus_bybit_replay_package import (
        CANONICAL_COLUMNS, build_manifest, canonical_timestamp_index,
        semantic_series_digest,
    )

    before = build_manifest(output_root)
    if before["semantic_dataset_sha256"] == ARCHIVE_SHA256:
        return {"status": "ALREADY_CANONICAL", "semantic_dataset_sha256": ARCHIVE_SHA256,
                "restored_chunk_ids": [], "paper_only": True, "live_trading_authority": False}
    reference = build_manifest(reference_root)
    if reference["semantic_dataset_sha256"] != ARCHIVE_SHA256:
        raise FrozenReplaySemanticsError("reference is not the frozen canonical dataset")
    sources = json.loads((output_root / "_source_manifest.json").read_text())
    bindings = verify_frozen_bulk_sources(sources)
    replacements = []
    for item in reference["files"]:
        relative = Path(item["path"])
        current = pd.read_parquet(output_root / relative).sort_values("timestamp").reset_index(drop=True)
        frozen = pd.read_parquet(reference_root / relative).sort_values("timestamp").reset_index(drop=True)
        for frame in (current, frozen):
            frame["timestamp"] = canonical_timestamp_index(pd.to_datetime(frame["timestamp"], utc=True))
        timestamps = current["timestamp"]
        permitted = timestamps.ge(pd.Timestamp("2024-04-01", tz="UTC")) & timestamps.lt(
            pd.Timestamp("2024-06-01", tz="UTC")
        )
        if semantic_series_digest(current.loc[~permitted]) != semantic_series_digest(frozen.loc[~permitted]):
            raise FrozenReplaySemanticsError("unexpected candle drift outside frozen bulk months")
        for column in CANONICAL_COLUMNS:
            current.loc[permitted, column] = frozen.loc[permitted, column].to_numpy()
        replacements.append((relative, current))

    with tempfile.TemporaryDirectory(prefix="nexus-frozen-replay-", dir=output_root.parent) as temp:
        staged = Path(temp)
        for relative, frame in replacements:
            target = staged / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            frame.to_parquet(target, index=False)
        if build_manifest(staged)["semantic_dataset_sha256"] != ARCHIVE_SHA256:
            raise FrozenReplaySemanticsError("staged restoration does not match frozen content")
        for relative, _ in replacements:
            os.replace(staged / relative, output_root / relative)
    return {
        "status": "RESTORED_FROZEN_BULK_SEMANTICS",
        "prior_semantic_dataset_sha256": before["semantic_dataset_sha256"],
        "semantic_dataset_sha256": ARCHIVE_SHA256,
        "restored_chunk_ids": ["41", "42"],
        "unchanged_official_raw_archives": bindings,
        "outside_month_candles_unchanged": True,
        "paper_only": True, "live_trading_authority": False,
    }


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
