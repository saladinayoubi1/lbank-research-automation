from __future__ import annotations

from pathlib import Path

import pandas as pd

import bybit_spot_archive_audit as audit


def write_official_archive(path: Path, symbol: str, audit_date: str) -> None:
    timestamps = pd.date_range(
        pd.Timestamp(audit_date, tz="UTC"),
        periods=24 * 60,
        freq="1min",
    )
    frame = pd.DataFrame(
        {
            "id": [str(index + 1) for index in range(len(timestamps))],
            "timestamp": timestamps.astype("int64") // 1_000_000,
            "price": 100.0 + (pd.Series(range(len(timestamps))) / 1000.0),
            "volume": 1.0,
            "side": ["buy", "sell"] * (len(timestamps) // 2),
            "rpi": 0,
        }
    )
    frame.to_csv(path, index=False, compression="gzip")


def test_archive_url_uses_official_spot_path():
    assert audit.archive_url("BTCUSDT", "2026-08-01") == (
        "https://public.bybit.com/spot/BTCUSDT/BTCUSDT_2026-08-01.csv.gz"
    )


def test_read_official_archive_normalizes_columns(tmp_path):
    path = tmp_path / "BTCUSDT_2026-08-01.csv.gz"
    write_official_archive(path, "BTCUSDT", "2026-08-01")
    frame, schema = audit.read_trade_archive(path)
    assert set(audit.REQUIRED_TRADE_COLUMNS).issubset(frame.columns)
    assert "trade_id" in frame.columns
    assert "symbol" not in frame.columns
    assert schema["timestamp_unit"] == "ms"
    assert schema["used_positional_schema"] is False
    assert frame["side"].iloc[:2].tolist() == ["Buy", "Sell"]


def test_read_positional_archive_supports_official_layout(tmp_path):
    path = tmp_path / "positional.csv.gz"
    rows = [
        ["1", "1785542400100", "100.0", "0.1", "buy", "0"],
        ["2", "1785542460100", "101.0", "0.2", "sell", "0"],
    ]
    pd.DataFrame(rows).to_csv(
        path,
        index=False,
        header=False,
        compression="gzip",
    )
    frame, schema = audit.read_trade_archive(path)
    assert schema["used_positional_schema"] is True
    assert schema["timestamp_unit"] == "ms"
    assert frame["price"].tolist() == [100.0, 101.0]
    assert frame["size"].tolist() == [0.1, 0.2]


def test_validate_trades_injects_expected_symbol():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-01T00:00:00Z", "2026-08-01T00:01:00Z"]
            ),
            "side": ["Buy", "Sell"],
            "size": [1.0, 1.0],
            "price": [100.0, 101.0],
            "trade_id": ["1", "2"],
        }
    )
    valid, quality = audit.validate_trades(frame, "BTCUSDT", "2026-08-01")
    assert len(valid) == 2
    assert valid["symbol"].unique().tolist() == ["BTCUSDT"]
    assert quality["invalid_symbol_rows"] == 0


def test_validate_trades_rejects_wrong_symbol_and_price():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                ["2026-08-01T00:00:00Z", "2026-08-01T00:01:00Z"]
            ),
            "symbol": ["BTCUSDT", "ETHUSDT"],
            "side": ["Buy", "Sell"],
            "size": [1.0, 1.0],
            "price": [100.0, -1.0],
        }
    )
    valid, quality = audit.validate_trades(frame, "BTCUSDT", "2026-08-01")
    assert len(valid) == 1
    assert quality["invalid_symbol_rows"] == 1
    assert quality["non_positive_price_rows"] == 1


def test_trade_aggregation_builds_complete_day():
    timestamps = pd.date_range(
        "2026-08-01T00:00:00Z",
        periods=24 * 60,
        freq="1min",
    )
    trades = pd.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": "BTCUSDT",
            "side": "Buy",
            "size": 1.0,
            "price": 100.0 + pd.Series(range(len(timestamps))) / 1000.0,
        }
    )
    for timeframe, expected_rows in [
        ("minute15", 96),
        ("hour1", 24),
        ("hour4", 6),
    ]:
        candles = audit.trades_to_candles(
            trades,
            "BTCUSDT",
            timeframe,
            "2026-08-01",
        )
        result = audit.audit_candles(
            candles,
            "BTCUSDT",
            timeframe,
            "2026-08-01",
        )
        assert result["rows"] == expected_rows
        assert result["missing_candles"] == 0
        assert result["audit_passed"] is True


def test_full_day_audit_detects_boundary_candle_missing():
    timestamps = pd.date_range(
        "2026-08-01T00:15:00Z",
        periods=95,
        freq="15min",
    )
    candles = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1.0,
        }
    )
    result = audit.audit_candles(
        candles,
        "BTCUSDT",
        "minute15",
        "2026-08-01",
    )
    assert result["missing_candles"] == 1
    assert result["gap_count"] == 1
    assert result["audit_passed"] is False


def test_build_report_passes_two_clean_archives(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    for symbol in audit.SYMBOLS:
        write_official_archive(
            source_root / audit.archive_filename(symbol, "2026-08-01"),
            symbol,
            "2026-08-01",
        )

    def downloader(symbol, audit_date, cache_root):
        path = source_root / audit.archive_filename(symbol, audit_date)
        return {
            "symbol": symbol,
            "audit_date": audit_date,
            "url": audit.archive_url(symbol, audit_date),
            "path": path.as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": "test",
            "http_status": 200,
        }

    report = audit.build_archive_audit_report(
        audit_date="2026-08-01",
        cache_root=tmp_path / "cache",
        downloader=downloader,
    )
    assert report["summary"]["archives_passed"] == 2
    assert report["summary"]["series_passed"] == 6
    assert report["summary"]["candidate_for_full_spot_archive_backfill"] is True


def test_build_report_survives_download_errors(tmp_path):
    def downloader(symbol, audit_date, cache_root):
        raise RuntimeError("unavailable")

    report = audit.build_archive_audit_report(
        audit_date="2026-08-01",
        cache_root=tmp_path,
        downloader=downloader,
    )
    assert report["summary"]["candidate_for_full_spot_archive_backfill"] is False
    assert report["summary"]["download_or_parse_errors"] == 2


def test_write_report_creates_four_files(tmp_path):
    report = {
        "generated_at_utc": "2026-08-03T00:00:00Z",
        "scope": {"audit_date": "2026-08-01"},
        "summary": {
            "candidate_for_full_spot_archive_backfill": False,
            "archives_passed": 0,
            "archives_expected": 2,
            "series_passed": 0,
            "series_expected": 6,
            "download_or_parse_errors": 2,
        },
        "archives": [],
        "series": [],
        "errors": [],
    }
    audit.write_report(report, tmp_path, clean=True)
    assert {path.name for path in tmp_path.iterdir()} == {
        "_bybit_spot_archive_audit.json",
        "_bybit_spot_archive_audit.md",
        "_bybit_spot_archive_series.csv",
        "_bybit_spot_archive_sources.csv",
    }
