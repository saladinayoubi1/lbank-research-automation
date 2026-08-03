from __future__ import annotations

import json

import pandas as pd
import pytest

import gap_inventory as inventory


def test_cached_fetcher_records_responses():
    calls = []

    def fetcher(symbol, timeframe, start):
        calls.append((symbol, timeframe, start))
        return [[start, 1, 1, 1, 1, 1]]

    cached = inventory.CachedKlineFetcher(fetcher)
    rows = cached("btc_usdt", "hour1", 1767225600)

    assert rows == [[1767225600, 1, 1, 1, 1, 1]]
    assert calls == [("btc_usdt", "hour1", 1767225600)]
    assert cached.responses[0]["requested_time_utc"] == "2026-01-01T00:00:00+00:00"


def test_diagnose_raw_row_ignores_non_missing_timestamp():
    missing = {pd.Timestamp("2026-01-01T00:15:00Z")}
    row = [int(pd.Timestamp("2026-01-01T00:00:00Z").timestamp()), 1, 1, 1, 1, 1]
    assert inventory.diagnose_raw_row(row, missing) is None


def test_diagnose_raw_row_marks_valid_missing_row():
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    row = [int(target.timestamp()), 10, 11, 9, 10.5, 4]
    result = inventory.diagnose_raw_row(row, {target})

    assert result is not None
    assert result["timestamp_utc"] == target.isoformat()
    assert result["canonical_valid"] is True
    assert result["validation_reasons"] == []


def test_diagnose_raw_row_records_multiple_reasons():
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    row = [int(target.timestamp()), 10, 9, 11, 10, -1]
    result = inventory.diagnose_raw_row(row, {target})

    assert result is not None
    assert result["canonical_valid"] is False
    assert result["validation_reasons"] == [
        "high_below_ohlc_max",
        "low_above_ohlc_min",
        "negative_volume",
    ]


def test_build_inventory_deduplicates_repeated_anchor_rows():
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    raw = [int(target.timestamp()), 10, 9, 8, 10, 5]
    responses = [
        {
            "symbol": "btc_usdt",
            "timeframe": "hour1",
            "requested_time_utc": "2026-01-01T00:00:00+00:00",
            "rows": [raw],
        },
        {
            "symbol": "btc_usdt",
            "timeframe": "hour1",
            "requested_time_utc": "2026-01-01T00:15:00+00:00",
            "rows": [raw],
        },
    ]

    result = inventory.build_inventory(
        responses,
        {("btc_usdt", "hour1"): {target}},
        total_source_missing=2,
    )

    assert result["summary"]["cached_api_responses"] == 2
    assert result["summary"]["unique_missing_timestamps_observed_raw"] == 1
    assert result["summary"]["unique_missing_timestamps_invalid"] == 1
    assert result["summary"]["unique_missing_timestamps_valid"] == 0
    assert result["summary"]["raw_missing_coverage_percent"] == pytest.approx(50.0)
    assert result["summary"]["unique_raw_rows"] == 1
    assert result["rows"][0]["observation_count"] == 2


def test_build_inventory_counts_valid_and_invalid_timestamps_separately():
    first = pd.Timestamp("2026-01-01T00:15:00Z")
    second = pd.Timestamp("2026-01-01T00:30:00Z")
    responses = [{
        "symbol": "btc_usdt",
        "timeframe": "hour1",
        "requested_time_utc": "2026-01-01T00:00:00+00:00",
        "rows": [
            [int(first.timestamp()), 10, 11, 9, 10, 1],
            [int(second.timestamp()), 10, 9, 8, 10, 1],
        ],
    }]

    result = inventory.build_inventory(
        responses,
        {("btc_usdt", "hour1"): {first, second}},
        total_source_missing=2,
    )

    assert result["summary"]["unique_missing_timestamps_observed_raw"] == 2
    assert result["summary"]["unique_missing_timestamps_invalid"] == 1
    assert result["summary"]["unique_missing_timestamps_valid"] == 1
    assert result["summary"]["raw_missing_coverage_percent"] == pytest.approx(100.0)


def test_collect_missing_sets_reads_only_existing_series(monkeypatch, tmp_path):
    monkeypatch.setattr(inventory, "SYMBOLS", ["btc_usdt", "eth_usdt"])
    monkeypatch.setattr(inventory, "TIMEFRAMES", ["minute15"])

    btc = tmp_path / "btc_usdt" / "minute15.parquet"
    btc.parent.mkdir(parents=True)
    btc.touch()

    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
        ])
    })

    missing_by_series, total = inventory.collect_missing_sets(
        tmp_path,
        frame_reader=lambda path: frame,
    )

    assert total == 1
    assert missing_by_series == {
        ("btc_usdt", "minute15"): {pd.Timestamp("2026-01-01T00:15:00Z")}
    }


def test_write_inventory_creates_json_markdown_and_csv(tmp_path):
    result = {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "summary": {
            "cached_api_responses": 1,
            "total_source_missing_candles": 1,
            "unique_missing_timestamps_observed_raw": 1,
            "unique_missing_timestamps_invalid": 1,
            "unique_missing_timestamps_valid": 0,
            "raw_missing_coverage_percent": 100.0,
            "unique_raw_rows": 1,
        },
        "rows": [{
            "symbol": "btc_usdt",
            "timeframe": "hour1",
            "timestamp_utc": "2026-01-01T00:15:00+00:00",
            "open": 10,
            "high": 9,
            "low": 8,
            "close": 10,
            "volume": 5,
            "validation_reasons": ["high_below_ohlc_max"],
            "canonical_valid": False,
            "observed_request_times_utc": ["2026-01-01T00:00:00+00:00"],
            "observation_count": 1,
        }],
    }

    inventory.write_inventory(result, tmp_path)

    loaded = json.loads((tmp_path / "_gap_inventory.json").read_text())
    assert loaded["summary"]["unique_raw_rows"] == 1
    assert "Raw missing coverage: 100.00%" in (
        tmp_path / "_gap_inventory.md"
    ).read_text()
    csv = pd.read_csv(tmp_path / "_gap_inventory.csv")
    assert csv.loc[0, "symbol"] == "btc_usdt"
