import json
from pathlib import Path

import pandas as pd

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_multipair_archive_snapshot_v2 as snapshot
from nexus_multipair_trusted_surface import SYMBOLS, TIMEFRAMES

SOURCE_SHA = "2" * 40


def _report():
    return {
        "configuration": {"start_date": snapshot.SOURCE_START_DATE, "end_date": snapshot.SOURCE_END_DATE, "symbols": list(SYMBOLS)},
        "summary": {"plan_units": 3, "plan_archives": 12, "completed_units": 3, "remaining_units": 0,
                    "run_failures": 0, "backfill_complete": True, "current_dataset_integrity_ok": True},
        "run_failures": [],
    }


def _seed(tmp_path: Path):
    state = tmp_path / "state"; state.mkdir()
    records = []
    for index, (month, symbol) in enumerate((m, s) for m in snapshot.SOURCE_MONTHS for s in SYMBOLS):
        start, end = snapshot._month_bounds(month); filename = f"{symbol}-{month}.csv.gz"
        records.append({
            "symbol": symbol, "unit_id": f"monthly:{month}", "unit_kind": "monthly", "filename": filename,
            "url": backfill.archive_url(symbol, filename), "start_date": start, "end_date": end,
            "http_status": 200, "size_bytes": 1000 + index, "sha256": f"{index + 1:064x}",
            "source_rows": 10000, "valid_trade_rows": 10000, "parser_engine": "c", "timestamp_unit": "ms",
            "invalid_numeric_rows": 0, "invalid_symbol_rows": 0, "invalid_side_rows": 0,
            "non_positive_price_rows": 0, "negative_size_rows": 0, "outside_range_rows": 0,
            "duplicate_trade_id_count": 0, "source_rows_skipped": 0, "malformed_csv_rows": 0,
        })
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(records), encoding="utf-8")
    for symbol in SYMBOLS:
        for timeframe in TIMEFRAMES:
            freq = {"minute15": "15min", "hour1": "1h", "hour4": "4h"}[timeframe]
            timestamps = pd.date_range("2026-04-01T00:00:00Z", periods=546 if timeframe == "hour4" else 700, freq=freq)
            base = pd.Series(range(len(timestamps)), dtype="float64") / 1000 + 100
            frame = pd.DataFrame({"timestamp": timestamps, "open": base, "high": base + 1, "low": base - 1,
                                  "close": base + .25, "volume": 1.0,
                                  "symbol": collector.canonical_symbol(symbol), "timeframe": timeframe})
            path = state / "bybit_market" / collector.canonical_symbol(symbol) / f"{timeframe}.parquet"
            path.parent.mkdir(parents=True, exist_ok=True); frame.loc[:, collector.CANONICAL_COLUMNS].to_parquet(path, index=False)
    return state


def test_v2_window_is_exact_three_month_surface_and_covers_500_4h_rows():
    assert snapshot.SOURCE_START_DATE == "2026-04-01"
    assert snapshot.SOURCE_END_DATE == "2026-06-30"
    assert snapshot.SOURCE_MONTHS == ("2026-04", "2026-05", "2026-06")
    assert snapshot.EXPECTED_SOURCE_ARCHIVES == 12
    assert snapshot._window_supports_history_limit() is True
    assert len(pd.date_range("2026-04-01T00:00:00Z", "2026-07-01T00:00:00Z", freq="4h", inclusive="left")) == 546


def test_v2_builds_verified_12_cell_snapshot(tmp_path):
    state = _seed(tmp_path); output = tmp_path / "snapshot"
    result = snapshot.build_snapshot_from_backfill(state_root=state, output_root=output, report=_report(), source_sha=SOURCE_SHA)
    assert snapshot.verify_snapshot(output, result)["decision"] == "pass"
    assert result["schema_version"] == snapshot.SCHEMA
    assert result["archive_source_count"] == 12 and result["cell_count"] == 12 and result["history_limit"] == 500
    assert result["runtime_freshness_claimed"] is False
    assert result["live_trading_authority"] is False and result["issue_984_state_touched"] is False


def test_v2_rejects_july_or_substituted_source(tmp_path):
    state = _seed(tmp_path)
    records = json.loads((state / backfill.SOURCE_MANIFEST_NAME).read_text())
    records[0]["unit_id"] = "monthly:2026-07"
    records[0]["filename"] = f"{records[0]['symbol']}-2026-07.csv.gz"
    records[0]["url"] = backfill.archive_url(records[0]["symbol"], records[0]["filename"])
    (state / backfill.SOURCE_MANIFEST_NAME).write_text(json.dumps(records), encoding="utf-8")
    try:
        snapshot.build_snapshot_from_backfill(state_root=state, output_root=tmp_path / "bad", report=_report(), source_sha=SOURCE_SHA)
    except snapshot.MultiPairArchiveSnapshotV2Error:
        pass
    else:
        raise AssertionError("July source must be outside the immutable v2 window")
