from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_archive_snapshot as archive_snapshot
import nexus_multipair_strategy_discovery as discovery
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "experiments" / "nexus_multipair_strategy_discovery_v2.json"
SOURCE_SHA = "b" * 40


def _report() -> dict:
    return {
        "configuration": {
            "start_date": archive_snapshot.SOURCE_START_DATE,
            "end_date": archive_snapshot.SOURCE_END_DATE,
            "symbols": list(SYMBOLS),
            "max_archives_per_run": archive_snapshot.EXPECTED_SOURCE_ARCHIVES,
        },
        "summary": {
            "plan_units": len(archive_snapshot.SOURCE_MONTHS),
            "plan_archives": archive_snapshot.EXPECTED_SOURCE_ARCHIVES,
            "completed_units": len(archive_snapshot.SOURCE_MONTHS),
            "remaining_units": 0,
            "units_completed_this_run": len(archive_snapshot.SOURCE_MONTHS),
            "archives_completed_this_run": archive_snapshot.EXPECTED_SOURCE_ARCHIVES,
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "run_failures": [],
    }


def _source_record(symbol: str, month: str, index: int) -> dict:
    filename = f"{symbol}-{month}.csv.gz"
    start_date, end_date = archive_snapshot._month_bounds(month)
    return {
        "symbol": symbol,
        "filename": filename,
        "url": backfill.archive_url(symbol, filename),
        "path": f"/cache/{filename}",
        "size_bytes": 1000 + index,
        "sha256": f"{index + 1:064x}",
        "http_status": 200,
        "download_attempts": 1,
        "loaded_from_cache": False,
        "used_positional_schema": False,
        "source_columns": ["trade_id", "timestamp", "price", "size", "side", "rpi"],
        "timestamp_unit": "ms",
        "source_header_columns": ["id", "timestamp", "price", "volume", "side", "rpi"],
        "extended_named_schema_columns": 0,
        "parser_engine": "c",
        "malformed_csv_rows": 0,
        "malformed_csv_line_samples": [],
        "source_rows_parsed": 10000,
        "source_rows_skipped": 0,
        "source_rows": 10000,
        "valid_trade_rows": 10000,
        "invalid_numeric_rows": 0,
        "invalid_symbol_rows": 0,
        "invalid_side_rows": 0,
        "non_positive_price_rows": 0,
        "negative_size_rows": 0,
        "outside_range_rows": 0,
        "duplicate_trade_id_count": 0,
        "unit_id": f"monthly:{month}",
        "unit_kind": "monthly",
        "start_date": start_date,
        "end_date": end_date,
    }


def _frame(symbol: str, timeframe: str) -> pd.DataFrame:
    freq = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}[timeframe]
    timestamps = pd.date_range("2026-05-01T00:00:00Z", periods=520, freq=freq)
    base = pd.Series(range(len(timestamps)), dtype="float64") / 1000.0 + 100.0
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": base,
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base + 0.25,
            "volume": 1.0,
            "symbol": collector.canonical_symbol(symbol),
            "timeframe": timeframe,
        }
    ).loc[:, collector.CANONICAL_COLUMNS]


def _archive_root(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    records: list[dict] = []
    index = 0
    for month in archive_snapshot.SOURCE_MONTHS:
        for symbol in SYMBOLS:
            records.append(_source_record(symbol, month, index))
            index += 1
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = state / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            _frame(symbol, timeframe).to_parquet(path, index=False)

    output = tmp_path / "archive-snapshot"
    value = archive_snapshot.build_snapshot_from_backfill(
        state_root=state,
        output_root=output,
        report=_report(),
        source_sha=SOURCE_SHA,
    )
    assert archive_snapshot.verify_snapshot(output, value)["decision"] == "pass"
    return output


def _manifest(tmp_path: Path, dataset_root: Path) -> Path:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    value["dataset"]["dataset_root"] = str(dataset_root)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_discovery_accepts_verified_official_archive_snapshot(tmp_path: Path) -> None:
    root = _archive_root(tmp_path)
    result = discovery.run(_manifest(tmp_path, root), tmp_path / "output", source_sha=SOURCE_SHA)
    assert discovery.verify_discovery(result)["decision"] == "pass"
    assert result["snapshot_schema_version"] == archive_snapshot.SCHEMA
    assert result["snapshot_data_origin"] == "official_public_bybit_spot_trade_archive_aggregated"
    assert result["snapshot_runtime_freshness_claimed"] is False
    assert result["snapshot_history_limit"] == archive_snapshot.HISTORY_LIMIT
    assert result["snapshot_as_of_ms"] == max(
        row["last_open_time_ms"]
        for row in json.loads((root / "snapshot-manifest.json").read_text(encoding="utf-8"))["cells"]
    )
    assert result["research_only"] is True
    assert result["automatic_paper_forward_started"] is False
    assert result["live_trading_authority"] is False


def test_discovery_rejects_unknown_snapshot_schema_before_evaluation(tmp_path: Path) -> None:
    root = _archive_root(tmp_path)
    path = root / "snapshot-manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["schema_version"] = "nexus.unknown-snapshot.v1"
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(discovery.MultiPairStrategyDiscoveryError, match="unsupported"):
        discovery.run(_manifest(tmp_path, root), tmp_path / "output", source_sha=SOURCE_SHA)


def test_discovery_rejects_tampered_archive_frame(tmp_path: Path) -> None:
    root = _archive_root(tmp_path)
    target = root / "bybit_market" / "SOLUSDT" / "hour4.parquet"
    frame = pd.read_parquet(target)
    frame.loc[0, "close"] = float(frame.loc[0, "close"]) * 1.5
    frame.to_parquet(target, index=False)
    with pytest.raises(discovery.MultiPairStrategyDiscoveryError, match="verification failed"):
        discovery.run(_manifest(tmp_path, root), tmp_path / "output", source_sha=SOURCE_SHA)
