import json
from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_archive_snapshot as snapshot
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES


SOURCE_SHA = "1" * 40


def _report():
    return {
        "configuration": {
            "start_date": snapshot.SOURCE_START_DATE,
            "end_date": snapshot.SOURCE_END_DATE,
            "symbols": list(SYMBOLS),
            "max_archives_per_run": snapshot.EXPECTED_SOURCE_ARCHIVES,
        },
        "summary": {
            "plan_units": 3,
            "plan_archives": 12,
            "completed_units": 3,
            "remaining_units": 0,
            "units_completed_this_run": 3,
            "archives_completed_this_run": 12,
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "run_failures": [],
    }


def _source_record(symbol: str, month: str, index: int):
    filename = f"{symbol}-{month}.csv.gz"
    start_date, end_date = snapshot._month_bounds(month)
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


def _frame(symbol: str, timeframe: str):
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


def _seed_backfill(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    records = []
    index = 0
    for month in snapshot.SOURCE_MONTHS:
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
    return state, records


def test_builds_exact_12_cell_500_row_archive_snapshot(tmp_path):
    state, _ = _seed_backfill(tmp_path)
    output = tmp_path / "snapshot"
    result = snapshot.build_snapshot_from_backfill(
        state_root=state, output_root=output, report=_report(), source_sha=SOURCE_SHA
    )
    verification = snapshot.verify_snapshot(output, result)
    assert verification["decision"] == "pass"
    assert result["archive_source_count"] == 12
    assert result["cell_count"] == 12
    assert result["history_limit"] == 500
    assert result["symbols"] == list(SYMBOLS)
    assert result["timeframes"] == list(TIMEFRAMES)
    assert result["data_origin"] == "official_public_bybit_spot_trade_archive_aggregated"
    assert result["runtime_freshness_claimed"] is False
    assert result["research_only"] is True
    assert result["paper_execution_started"] is False
    assert result["live_trading_authority"] is False
    assert result["private_credentials_used"] is False
    assert result["automatic_strategy_promotion"] is False
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            frame = pd.read_parquet(output / "bybit_market" / symbol / f"{timeframe}.parquet")
            assert len(frame) == 500
            assert frame.columns.tolist() == snapshot._REQUIRED_COLUMNS
            assert set(frame["symbol"]) == {symbol}
            assert set(frame["timeframe"]) == {timeframe}


def test_rejects_substituted_archive_url(tmp_path):
    state, records = _seed_backfill(tmp_path)
    records[0]["url"] = "https://example.invalid/substitution.csv.gz"
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(records), encoding="utf-8")
    with pytest.raises(snapshot.MultiPairArchiveSnapshotError, match="provenance failed closed"):
        snapshot.build_snapshot_from_backfill(
            state_root=state, output_root=tmp_path / "out", report=_report(), source_sha=SOURCE_SHA
        )


def test_rejects_missing_monthly_source_archive(tmp_path):
    state, records = _seed_backfill(tmp_path)
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(records[:-1]), encoding="utf-8")
    with pytest.raises(snapshot.MultiPairArchiveSnapshotError, match="exactly 12 monthly archives"):
        snapshot.build_snapshot_from_backfill(
            state_root=state, output_root=tmp_path / "out", report=_report(), source_sha=SOURCE_SHA
        )


def test_verifier_rejects_tampered_frame(tmp_path):
    state, _ = _seed_backfill(tmp_path)
    output = tmp_path / "snapshot"
    result = snapshot.build_snapshot_from_backfill(
        state_root=state, output_root=output, report=_report(), source_sha=SOURCE_SHA
    )
    path = output / "bybit_market" / "SOLUSDT" / "hour4.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, "close"] = float(frame.loc[0, "close"]) + 7.0
    frame.to_parquet(path, index=False)
    assert snapshot.verify_snapshot(output, result)["decision"] == "reject"


def test_pack_is_deterministic_and_contains_only_verified_snapshot(tmp_path):
    state, _ = _seed_backfill(tmp_path)
    output = tmp_path / "snapshot"
    snapshot.build_snapshot_from_backfill(
        state_root=state, output_root=output, report=_report(), source_sha=SOURCE_SHA
    )
    first = tmp_path / "one.zip"
    second = tmp_path / "two.zip"
    first_sha = snapshot.deterministic_pack(output, first)
    second_sha = snapshot.deterministic_pack(output, second)
    assert first_sha == second_sha
    assert first.read_bytes() == second.read_bytes()


def test_rejects_backfill_that_is_not_complete_and_integrity_clean(tmp_path):
    state, _ = _seed_backfill(tmp_path)
    report = _report()
    report["summary"]["current_dataset_integrity_ok"] = False
    with pytest.raises(snapshot.MultiPairArchiveSnapshotError, match="did not complete"):
        snapshot.build_snapshot_from_backfill(
            state_root=state, output_root=tmp_path / "out", report=report, source_sha=SOURCE_SHA
        )
