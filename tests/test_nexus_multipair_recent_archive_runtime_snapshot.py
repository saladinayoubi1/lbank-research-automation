from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_recent_archive_runtime_snapshot as recent
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


SOURCE_SHA = "7" * 40
LATEST = "2026-09-02"
ACQUIRED_MS = int(pd.Timestamp("2026-09-03T12:00:00Z").timestamp() * 1000)
PLAN_UNITS = [
    {
        "unit_id": "monthly:2026-07",
        "kind": "monthly",
        "start_date": "2026-07-01",
        "end_date": "2026-07-31",
        "filenames": {symbol: f"{symbol}-2026-07.csv.gz" for symbol in SYMBOLS},
    },
    {
        "unit_id": "monthly:2026-08",
        "kind": "monthly",
        "start_date": "2026-08-01",
        "end_date": "2026-08-31",
        "filenames": {symbol: f"{symbol}-2026-08.csv.gz" for symbol in SYMBOLS},
    },
    {
        "unit_id": "daily:2026-09-01",
        "kind": "daily",
        "start_date": "2026-09-01",
        "end_date": "2026-09-01",
        "filenames": {symbol: f"{symbol}_2026-09-01.csv.gz" for symbol in SYMBOLS},
    },
    {
        "unit_id": "daily:2026-09-02",
        "kind": "daily",
        "start_date": "2026-09-02",
        "end_date": "2026-09-02",
        "filenames": {symbol: f"{symbol}_2026-09-02.csv.gz" for symbol in SYMBOLS},
    },
]


def _inventory(symbol: str, dates: tuple[str, ...]) -> backfill.ArchiveInventory:
    return backfill.ArchiveInventory(
        symbol=symbol,
        monthly={"2026-07": f"{symbol}-2026-07.csv.gz", "2026-08": f"{symbol}-2026-08.csv.gz"},
        daily={date: f"{symbol}_{date}.csv.gz" for date in dates},
    )


def _source_row(unit: dict, symbol: str, index: int) -> dict:
    filename = unit["filenames"][symbol]
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
        "unit_id": unit["unit_id"],
        "unit_kind": unit["kind"],
        "start_date": unit["start_date"],
        "end_date": unit["end_date"],
    }


def _frame(symbol: str, timeframe: str) -> pd.DataFrame:
    freq = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}[timeframe]
    step = pd.Timedelta(freq)
    end = pd.Timestamp("2026-09-03T00:00:00Z") - step
    timestamps = pd.date_range(end=end, periods=260, freq=freq)
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


def _seed(tmp_path: Path) -> tuple[Path, dict]:
    state = tmp_path / "state"
    state.mkdir()
    plan = {
        "generated_at_utc": "2026-09-03T12:00:00+00:00",
        "start_date": "2026-07-01",
        "end_date": LATEST,
        "symbols": list(SYMBOLS),
        "total_units": len(PLAN_UNITS),
        "monthly_units": 2,
        "daily_units": 2,
        "total_archives": len(PLAN_UNITS) * len(SYMBOLS),
        "unavailable_dates": [],
        "units": PLAN_UNITS,
    }
    (state / backfill.PLAN_NAME).write_text(json.dumps(plan), encoding="utf-8")
    sources = []
    index = 0
    for unit in PLAN_UNITS:
        for symbol in SYMBOLS:
            sources.append(_source_row(unit, symbol, index))
            index += 1
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(sources), encoding="utf-8")
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            path = state / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True)
            _frame(symbol, timeframe).to_parquet(path, index=False)
    report = {
        "configuration": {
            "start_date": "2026-07-01",
            "end_date": LATEST,
            "symbols": list(SYMBOLS),
            "max_archives_per_run": len(sources),
        },
        "summary": {
            "plan_units": len(PLAN_UNITS),
            "plan_archives": len(sources),
            "completed_units": len(PLAN_UNITS),
            "remaining_units": 0,
            "units_completed_this_run": len(PLAN_UNITS),
            "archives_completed_this_run": len(sources),
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "run_failures": [],
    }
    return state, report


def test_latest_common_complete_day_is_selected_fail_closed() -> None:
    inventories = {
        "BTCUSDT": _inventory("BTCUSDT", ("2026-09-01", "2026-09-02")),
        "ETHUSDT": _inventory("ETHUSDT", ("2026-09-01", "2026-09-02")),
        "SOLUSDT": _inventory("SOLUSDT", ("2026-09-01", "2026-09-02")),
        "XRPUSDT": _inventory("XRPUSDT", ("2026-09-01",)),
    }
    now_ms = int(pd.Timestamp("2026-09-02T12:00:00Z").timestamp() * 1000)
    assert recent.select_latest_common_complete_date(inventories, now_ms=now_ms) == "2026-09-01"


def test_stale_common_archive_day_is_rejected() -> None:
    inventories = {
        symbol: _inventory(symbol, ("2026-08-30",)) for symbol in SYMBOLS
    }
    now_ms = int(pd.Timestamp("2026-09-03T12:00:00Z").timestamp() * 1000)
    with pytest.raises(recent.MultiPairRecentArchiveRuntimeError, match="stale"):
        recent.select_latest_common_complete_date(inventories, now_ms=now_ms)


def test_builds_verified_recent_12_cell_240_row_snapshot_without_live_freshness_claim(tmp_path: Path) -> None:
    state, report = _seed(tmp_path)
    output = tmp_path / "snapshot"
    value = recent.build_snapshot_from_backfill(
        state_root=state,
        output_root=output,
        report=report,
        source_sha=SOURCE_SHA,
        acquired_at_ms=ACQUIRED_MS,
        latest_common_complete_date=LATEST,
    )
    verification = recent.verify_recent_archive_runtime_snapshot(
        output,
        value,
        source_sha=SOURCE_SHA,
        now_ms=ACQUIRED_MS + 5 * 60 * 1000,
    )
    assert verification["decision"] == "pass"
    assert value["schema_version"] == recent.SCHEMA
    assert value["data_origin"] == recent.DATA_ORIGIN
    assert value["runtime_requalification_recency_verified"] is True
    assert value["live_freshness_claimed"] is False
    assert value["latest_common_complete_date"] == LATEST
    assert value["data_as_of_ms"] == int(pd.Timestamp("2026-09-03T00:00:00Z").timestamp() * 1000)
    assert value["source_lag_ms_at_acquisition"] == 12 * 60 * 60 * 1000
    assert value["archive_source_count"] == 16
    assert value["cell_count"] == 12
    assert value["history_limit"] == 240
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            frame = pd.read_parquet(output / "bybit_market" / symbol / f"{timeframe}.parquet")
            assert len(frame) == 240
            assert set(frame["symbol"]) == {symbol}
            assert set(frame["timeframe"]) == {timeframe}


def test_consumer_rejects_recent_archive_after_source_lag_bound(tmp_path: Path) -> None:
    state, report = _seed(tmp_path)
    output = tmp_path / "snapshot"
    value = recent.build_snapshot_from_backfill(
        state_root=state,
        output_root=output,
        report=report,
        source_sha=SOURCE_SHA,
        acquired_at_ms=ACQUIRED_MS,
        latest_common_complete_date=LATEST,
    )
    stale_now = int(pd.Timestamp("2026-09-04T13:00:00Z").timestamp() * 1000)
    verification = recent.verify_recent_archive_runtime_snapshot(
        output,
        value,
        source_sha=SOURCE_SHA,
        now_ms=stale_now,
        max_transport_age_ms=3 * 24 * 60 * 60 * 1000,
    )
    assert verification["decision"] == "reject"
    assert verification["checks"]["source_recency"] is False


def test_live_freshness_claim_tamper_is_rejected(tmp_path: Path) -> None:
    state, report = _seed(tmp_path)
    output = tmp_path / "snapshot"
    value = recent.build_snapshot_from_backfill(
        state_root=state,
        output_root=output,
        report=report,
        source_sha=SOURCE_SHA,
        acquired_at_ms=ACQUIRED_MS,
        latest_common_complete_date=LATEST,
    )
    value["live_freshness_claimed"] = True
    assert recent.verify_recent_archive_runtime_snapshot(
        output, value, source_sha=SOURCE_SHA, now_ms=ACQUIRED_MS
    )["decision"] == "reject"


def test_recent_archive_pack_is_deterministic(tmp_path: Path) -> None:
    state, report = _seed(tmp_path)
    output = tmp_path / "snapshot"
    recent.build_snapshot_from_backfill(
        state_root=state,
        output_root=output,
        report=report,
        source_sha=SOURCE_SHA,
        acquired_at_ms=ACQUIRED_MS,
        latest_common_complete_date=LATEST,
    )
    first = tmp_path / "a.zip"
    second = tmp_path / "b.zip"
    assert recent.deterministic_pack(output, first) == recent.deterministic_pack(output, second)
    assert first.read_bytes() == second.read_bytes()
