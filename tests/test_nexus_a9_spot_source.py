from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

import bybit_spot_archive_collector as collector
import bybit_spot_backfill as backfill
import nexus_a9_spot_source as source


def _write_frame(root, symbol):
    canonical = collector.canonical_symbol(symbol)
    index = pd.date_range(
        source.ANALYSIS_START,
        source.ANALYSIS_END_EXCLUSIVE,
        freq="15min",
        inclusive="left",
    )
    x = np.arange(len(index), dtype=float)
    close = 100.0 + x * 0.001
    frame = pd.DataFrame(
        {
            "timestamp": index,
            "open": close - 0.01,
            "high": close + 0.05,
            "low": close - 0.06,
            "close": close,
            "volume": 10.0,
            "symbol": canonical,
            "timeframe": source.TIMEFRAME,
        }
    )
    path = root / "bybit_market" / canonical
    path.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path / "minute15.parquet", index=False)


def _source_row(symbol, day):
    filename = f"{symbol}_{day}.csv.gz"
    return {
        "symbol": symbol,
        "filename": filename,
        "url": backfill.archive_url(symbol, filename),
        "path": f"cache/{filename}",
        "size_bytes": 123456,
        "sha256": "a" * 64,
        "http_status": 200,
        "download_attempts": 1,
        "loaded_from_cache": False,
        "parser_engine": "c",
        "timestamp_unit": "ms",
        "source_rows": 100,
        "valid_trade_rows": 100,
        "unit_id": f"daily:{day}",
        "unit_kind": "daily",
        "start_date": day,
        "end_date": day,
        "invalid_numeric_rows": 0,
        "invalid_symbol_rows": 0,
        "invalid_side_rows": 0,
        "non_positive_price_rows": 0,
        "negative_size_rows": 0,
        "outside_range_rows": 0,
        "duplicate_trade_id_count": 0,
        "source_rows_skipped": 0,
        "malformed_csv_rows": 0,
    }


def _write_source_state(root):
    for symbol in source.SYMBOLS:
        _write_frame(root, symbol)
    rows = [
        _source_row(symbol, day)
        for day in source.EXPECTED_DAYS
        for symbol in source.SYMBOLS
    ]
    (root / backfill.SOURCE_MANIFEST_NAME).write_text(
        json.dumps(rows, indent=2),
        encoding="utf-8",
    )
    report = {
        "configuration": {
            "start_date": source.SOURCE_START_DATE,
            "end_date": source.SOURCE_END_DATE,
            "symbols": list(source.SYMBOLS),
            "max_archives_per_run": source.EXPECTED_ARCHIVES,
        },
        "summary": {
            "plan_units": len(source.EXPECTED_DAYS),
            "plan_archives": source.EXPECTED_ARCHIVES,
            "completed_units": len(source.EXPECTED_DAYS),
            "remaining_units": 0,
            "units_completed_this_run": len(source.EXPECTED_DAYS),
            "archives_completed_this_run": source.EXPECTED_ARCHIVES,
            "run_failures": 0,
            "backfill_complete": True,
            "current_dataset_integrity_ok": True,
        },
        "run_failures": [],
    }
    (root / backfill.REPORT_NAME).write_text(json.dumps(report), encoding="utf-8")
    return report


def test_a9_spot_proof_is_btc_eth_daily_exact_window(tmp_path):
    report = _write_source_state(tmp_path)
    proof = source.build_proof(tmp_path, report)
    (tmp_path / source.PROOF_NAME).write_text(json.dumps(proof), encoding="utf-8")
    source.verify_proof(tmp_path, proof)

    assert proof["symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert proof["archive_granularity"] == "daily"
    assert proof["archive_source_count"] == 60
    assert {row["date"] for row in proof["archive_sources"]} == set(source.EXPECTED_DAYS)
    assert {row["unit_kind"] for row in proof["archive_sources"]} == {"daily"}
    assert proof["source_window_start"] == "2026-07-03"
    assert proof["source_window_end_inclusive"] == "2026-08-01"
    assert proof["analysis_start_utc"] == "2026-07-03T00:00:00+00:00"
    assert proof["analysis_end_exclusive_utc"] == "2026-08-02T00:00:00+00:00"
    assert {cell["analysis_rows"] for cell in proof["cells"]} == {2880}
    assert proof["research_only"] is True
    assert proof["automatic_strategy_promotion"] is False
    assert proof["live_trading_authority"] is False


def test_a9_spot_proof_rejects_tampered_analysis_bytes(tmp_path):
    report = _write_source_state(tmp_path)
    proof = source.build_proof(tmp_path, report)
    path = tmp_path / "bybit_market" / "btc_usdt" / "minute15.parquet"
    frame = pd.read_parquet(path)
    target = frame.index[frame["timestamp"] == pd.Timestamp("2026-07-03T01:00:00Z")][0]
    frame.loc[target, "close"] = frame.loc[target, "close"] + 1.0
    frame.loc[target, "high"] = max(frame.loc[target, "high"], frame.loc[target, "close"])
    frame.to_parquet(path, index=False)
    with pytest.raises(source.A9SpotSourceError):
        source.verify_proof(tmp_path, proof)
