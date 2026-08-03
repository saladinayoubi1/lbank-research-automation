from __future__ import annotations

import json

import pandas as pd
import pytest

import contiguous_segments as segments


def make_frame(
    timestamps,
    symbol="btc_usdt",
    timeframe="hour1",
):
    count = len(timestamps)
    return pd.DataFrame({
        "timestamp": pd.to_datetime(timestamps, utc=True),
        "open": [100.0] * count,
        "high": [101.0] * count,
        "low": [99.0] * count,
        "close": [100.5] * count,
        "volume": [10.0] * count,
        "symbol": [symbol] * count,
        "timeframe": [timeframe] * count,
    })


def test_normalize_series_frame_requires_canonical_column_order():
    frame = make_frame(["2026-01-01T00:00:00Z"])[
        list(reversed(segments.EXPECTED_COLUMNS))
    ]
    with pytest.raises(segments.SegmentAnalysisError, match="Unexpected schema"):
        segments.normalize_series_frame(frame, "btc_usdt", "hour1")


def test_normalize_series_frame_rejects_wrong_identity():
    frame = make_frame(
        ["2026-01-01T00:00:00Z"],
        symbol="eth_usdt",
    )
    with pytest.raises(segments.SegmentAnalysisError, match="Unexpected symbol"):
        segments.normalize_series_frame(frame, "btc_usdt", "hour1")


def test_timestamp_diagnostics_counts_gaps_duplicates_and_off_grid():
    timestamps = pd.Series(pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-01-01T02:00:00Z",
        "2026-01-01T03:30:00Z",
    ]))
    result = segments.timestamp_diagnostics(timestamps, "hour1")

    assert result["duplicate_count"] == 1
    assert result["off_grid_count"] == 1
    assert result["expected_rows"] == 4
    assert result["missing_candles"] == 1


def test_split_contiguous_timestamps_creates_maximal_blocks():
    timestamps = pd.DatetimeIndex(pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T03:00:00Z",
        "2026-01-01T04:00:00Z",
        "2026-01-01T07:00:00Z",
    ]))
    result = segments.split_contiguous_timestamps(timestamps, "hour1")

    assert [len(block) for block in result] == [2, 2, 1]
    assert result[1][0] == pd.Timestamp("2026-01-01T03:00:00Z")


def test_gap_candles_between_reports_aligned_gap():
    assert segments.gap_candles_between(
        pd.Timestamp("2026-01-01T01:00:00Z"),
        pd.Timestamp("2026-01-01T04:00:00Z"),
        "hour1",
    ) == 2


def test_gap_candles_between_returns_none_for_off_grid_gap():
    assert segments.gap_candles_between(
        pd.Timestamp("2026-01-01T01:00:00Z"),
        pd.Timestamp("2026-01-01T02:30:00Z"),
        "hour1",
    ) is None


def test_analyze_series_segments_reports_largest_block_and_boundaries():
    frame = make_frame([
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
        "2026-01-01T03:00:00Z",
        "2026-01-01T04:00:00Z",
        "2026-01-01T05:00:00Z",
    ])
    summary, rows = segments.analyze_series_segments(
        frame,
        "btc_usdt",
        "hour1",
        minimum_segment_rows=3,
    )

    assert summary["missing_candles"] == 1
    assert summary["segment_count"] == 2
    assert summary["largest_segment_index"] == 2
    assert summary["largest_segment_rows"] == 3
    assert summary["largest_segment_share"] == pytest.approx(0.6)
    assert summary["segments_meeting_minimum"] == 1
    assert rows[0]["gap_after_candles"] == 1
    assert rows[1]["gap_before_candles"] == 1
    assert rows[1]["meets_minimum_rows"] is True


def test_analyze_series_segments_does_not_bridge_duplicates():
    frame = make_frame([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
    ])
    summary, rows = segments.analyze_series_segments(
        frame, "btc_usdt", "hour1"
    )

    assert summary["rows"] == 3
    assert summary["unique_rows"] == 2
    assert summary["duplicate_count"] == 1
    assert summary["segment_count"] == 1
    assert summary["internally_clean_segments"] is False
    assert rows[0]["rows"] == 2


def test_build_segment_report_aggregates_series(monkeypatch, tmp_path):
    monkeypatch.setattr(segments, "SYMBOLS", ["btc_usdt", "eth_usdt"])
    monkeypatch.setattr(segments, "TIMEFRAMES", ["hour1"])

    frames = {
        "btc_usdt": make_frame([
            "2026-01-01T00:00:00Z",
            "2026-01-01T01:00:00Z",
        ]),
        "eth_usdt": make_frame([
            "2026-01-01T00:00:00Z",
            "2026-01-01T02:00:00Z",
        ], symbol="eth_usdt"),
    }
    for symbol in frames:
        path = tmp_path / symbol / "hour1.parquet"
        path.parent.mkdir(parents=True)
        path.touch()

    report = segments.build_segment_report(
        tmp_path,
        minimum_segment_rows=2,
        frame_reader=lambda path: frames[path.parent.name],
    )

    assert report["summary"]["total_series"] == 2
    assert report["summary"]["series_with_single_segment"] == 1
    assert report["summary"]["series_with_multiple_segments"] == 1
    assert report["summary"]["total_segments"] == 3
    assert report["summary"]["total_missing_candles"] == 1


def test_write_segment_report_creates_json_markdown_and_csv(tmp_path):
    frame = make_frame([
        "2026-01-01T00:00:00Z",
        "2026-01-01T01:00:00Z",
    ])
    summary, rows = segments.analyze_series_segments(
        frame, "btc_usdt", "hour1", minimum_segment_rows=2
    )
    report = {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "input_root": "data/market",
        "minimum_segment_rows": 2,
        "summary": {
            "total_series": 1,
            "series_with_multiple_segments": 0,
            "series_with_single_segment": 1,
            "total_segments": 1,
            "segments_meeting_minimum": 1,
            "series_with_large_segment": 1,
            "total_missing_candles": 0,
            "total_duplicates": 0,
            "total_off_grid": 0,
        },
        "series": [summary],
        "segments": rows,
    }

    segments.write_segment_report(report, tmp_path, clean=True)

    loaded = json.loads(
        (tmp_path / "_contiguous_segments.json").read_text()
    )
    assert loaded["summary"]["total_segments"] == 1
    assert "LBank Contiguous Segment Analysis" in (
        tmp_path / "_contiguous_segments.md"
    ).read_text()
    assert pd.read_csv(tmp_path / "_contiguous_series.csv").loc[0, "symbol"] == (
        "btc_usdt"
    )
    assert pd.read_csv(tmp_path / "_contiguous_segments.csv").loc[0, "rows"] == 2
