from __future__ import annotations

import pandas as pd

import bybit_data_audit


def make_rows(interval_minutes: int, count: int = 1000):
    timestamps = pd.date_range(
        "2026-01-01T00:00:00Z",
        periods=count,
        freq=f"{interval_minutes}min",
    )
    return [
        [str(int(ts.timestamp() * 1000)), "100", "102", "99", "101", "5", "500"]
        for ts in reversed(timestamps)
    ]


def test_closed_candle_end_uses_last_completed_interval():
    now = pd.Timestamp("2026-08-03T04:07:00Z")
    result = bybit_data_audit.closed_candle_end_ms("15", now=now)
    assert pd.to_datetime(result, unit="ms", utc=True) == pd.Timestamp(
        "2026-08-03T03:45:00Z"
    )


def test_parse_kline_rows_sorts_reverse_api_output():
    frame, quality = bybit_data_audit.parse_kline_rows(
        make_rows(15, count=3), "BTCUSDT", "15"
    )
    assert frame["timestamp"].is_monotonic_increasing
    assert quality == {
        "short_row_count": 0,
        "non_numeric_count": 0,
        "invalid_ohlc_count": 0,
        "negative_volume_count": 0,
    }


def test_parse_kline_rows_detects_invalid_ohlc():
    rows = [["1767225600000", "100", "99", "98", "100", "1", "100"]]
    _, quality = bybit_data_audit.parse_kline_rows(rows, "BTCUSDT", "15")
    assert quality["invalid_ohlc_count"] == 1


def test_verify_spot_instrument_requires_one_match():
    def fetch_json(path, params):
        return {
            "retCode": 0,
            "result": {
                "list": [{
                    "symbol": "BTCUSDT",
                    "status": "Trading",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                }]
            },
        }

    result = bybit_data_audit.verify_spot_instrument("BTCUSDT", fetch_json)
    assert result["found"] is True
    assert result["status"] == "Trading"


def test_audit_kline_series_passes_contiguous_rows():
    def fetch_json(path, params):
        return {
            "retCode": 0,
            "result": {
                "category": "spot",
                "symbol": params["symbol"],
                "list": make_rows(15),
            },
        }

    result = bybit_data_audit.audit_kline_series(
        "BTCUSDT",
        "15",
        fetch_json=fetch_json,
        now=pd.Timestamp("2026-08-03T04:07:00Z"),
    )
    assert result["rows"] == 1000
    assert result["missing_candles"] == 0
    assert result["audit_passed"] is True


def test_build_report_marks_clean_universe_as_candidate(monkeypatch):
    def fetch_json(path, params):
        if path.endswith("instruments-info"):
            symbol = params["symbol"]
            return {
                "retCode": 0,
                "result": {
                    "list": [{
                        "symbol": symbol,
                        "status": "Trading",
                        "baseCoin": symbol.removesuffix("USDT"),
                        "quoteCoin": "USDT",
                    }]
                },
            }
        interval_minutes = {"15": 15, "60": 60, "240": 240}[params["interval"]]
        return {
            "retCode": 0,
            "result": {
                "category": "spot",
                "symbol": params["symbol"],
                "list": make_rows(interval_minutes),
            },
        }

    report = bybit_data_audit.build_audit_report(
        request_pause_seconds=0,
        fetch_json=fetch_json,
        now=pd.Timestamp("2026-08-03T04:07:00Z"),
    )
    assert report["summary"]["series_passed"] == 6
    assert report["summary"]["candidate_for_full_backfill"] is True


def test_build_report_survives_request_errors():
    def fetch_json(path, params):
        raise RuntimeError("blocked")

    report = bybit_data_audit.build_audit_report(
        request_pause_seconds=0,
        fetch_json=fetch_json,
    )
    assert report["summary"]["candidate_for_full_backfill"] is False
    assert report["summary"]["request_errors"] == 6
    assert len(report["instruments"]) == 2


def test_write_report_creates_three_files(tmp_path):
    report = {
        "generated_at_utc": "2026-08-03T00:00:00Z",
        "summary": {
            "candidate_for_full_backfill": False,
            "instruments_trading": 0,
            "instruments_expected": 2,
            "series_passed": 0,
            "series_expected": 6,
            "request_errors": 0,
        },
        "series": [],
        "errors": [],
    }
    bybit_data_audit.write_report(report, tmp_path, clean=True)
    assert {path.name for path in tmp_path.iterdir()} == {
        "_bybit_data_audit.json",
        "_bybit_data_audit.md",
        "_bybit_data_audit.csv",
    }
