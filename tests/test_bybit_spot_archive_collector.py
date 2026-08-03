from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

import bybit_spot_archive_collector as collector


def write_archive(path: Path, audit_date: str) -> None:
    timestamps = pd.date_range(
        pd.Timestamp(audit_date, tz="UTC"),
        periods=24 * 60,
        freq="1min",
    )
    frame = pd.DataFrame(
        {
            "id": [str(index + 1) for index in range(len(timestamps))],
            "timestamp": timestamps.astype("int64") // 1_000_000,
            "price": 100.0 + pd.Series(range(len(timestamps))) / 1000.0,
            "volume": 1.0,
            "side": ["buy", "sell"] * (len(timestamps) // 2),
            "rpi": 0,
        }
    )
    frame.to_csv(path, index=False, compression="gzip")


def complete_candles(
    start_date: str,
    end_date: str,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    timestamps = collector.expected_index(start_date, end_date, timeframe)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
            "symbol": collector.canonical_symbol(symbol),
            "timeframe": timeframe,
        }
    )


def test_canonical_symbol():
    assert collector.canonical_symbol("BTCUSDT") == "btc_usdt"
    assert collector.canonical_symbol("ethusdt") == "eth_usdt"


def test_canonical_symbol_rejects_non_usdt():
    with pytest.raises(collector.BybitCollectorError, match="Unsupported"):
        collector.canonical_symbol("BTCUSD")


def test_inclusive_dates_and_reversed_range():
    assert collector.inclusive_audit_dates("2026-07-30", "2026-08-01") == [
        "2026-07-30",
        "2026-07-31",
        "2026-08-01",
    ]
    with pytest.raises(collector.BybitCollectorError, match="before"):
        collector.inclusive_audit_dates("2026-08-01", "2026-07-30")


def test_expected_index_counts_full_days():
    assert len(collector.expected_index("2026-07-30", "2026-08-01", "minute15")) == 288
    assert len(collector.expected_index("2026-07-30", "2026-08-01", "hour1")) == 72
    assert len(collector.expected_index("2026-07-30", "2026-08-01", "hour4")) == 18


def test_evaluate_complete_series_is_ready():
    frame = complete_candles(
        "2026-07-30",
        "2026-08-01",
        "BTCUSDT",
        "minute15",
    )
    normalized, status = collector.evaluate_series(
        frame,
        "BTCUSDT",
        "minute15",
        "2026-07-30",
        "2026-08-01",
    )
    assert len(normalized) == 288
    assert status["missing_candles"] == 0
    assert status["integrity_ok"] is True
    assert status["status"] == "ready"


def test_evaluate_series_detects_missing_and_duplicate():
    frame = complete_candles(
        "2026-08-01",
        "2026-08-01",
        "BTCUSDT",
        "hour1",
    )
    frame = pd.concat([frame.drop(index=0), frame.iloc[[1]]], ignore_index=True)
    _, status = collector.evaluate_series(
        frame,
        "BTCUSDT",
        "hour1",
        "2026-08-01",
        "2026-08-01",
    )
    assert status["missing_candles"] == 1
    assert status["duplicate_count"] == 1
    assert status["integrity_ok"] is False


def test_archive_quality_reports_failures():
    passed, failures = collector.validate_archive_quality(
        {
            "valid_trade_rows": 10,
            "invalid_numeric_rows": 1,
            "invalid_symbol_rows": 0,
            "invalid_side_rows": 0,
            "non_positive_price_rows": 0,
            "negative_size_rows": 0,
            "outside_audit_day_rows": 0,
            "duplicate_trade_id_count": 0,
        }
    )
    assert passed is False
    assert failures == ["invalid_numeric_rows"]


def test_build_collection_writes_six_parquets_and_reports(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        write_archive(
            source_root / f"{symbol}_2026-08-01.csv.gz",
            "2026-08-01",
        )

    def downloader(symbol, audit_date, cache_root):
        path = source_root / f"{symbol}_{audit_date}.csv.gz"
        return {
            "symbol": symbol,
            "audit_date": audit_date,
            "url": f"test://{path.name}",
            "path": path.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": "test",
            "http_status": 200,
            "download_attempts": 1,
            "loaded_from_cache": False,
        }

    output = tmp_path / "output"
    report = collector.build_collection(
        start_date="2026-08-01",
        end_date="2026-08-01",
        output_root=output,
        cache_root=tmp_path / "cache",
        clean=True,
        downloader=downloader,
    )
    assert report["summary"]["collector_ok"] is True
    assert report["summary"]["ready_series"] == 6
    assert len(list(output.glob("*/*.parquet"))) == 6
    assert (output / "_collection_report.json").exists()
    assert (output / "_backfill_status.csv").exists()
    assert (output / "_source_manifest.json").exists()
