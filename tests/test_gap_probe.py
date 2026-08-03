from __future__ import annotations

import importlib
import json
import sys
import types

import pandas as pd
import pytest


def load_module(monkeypatch):
    fake_main = types.ModuleType("main")
    fake_main.SYMBOLS = ["btc_usdt", "eth_usdt"]
    fake_main.TIMEFRAMES = ["minute15"]
    fake_main.TIMEFRAME_SECONDS = {"minute15": 900}
    fake_main.get_klines = lambda *args, **kwargs: []
    fake_main.rows_to_frame = lambda rows, symbol, timeframe: pd.DataFrame(
        {"timestamp": pd.Series(dtype="datetime64[ns, UTC]")}
    )

    fake_gap_repair = types.ModuleType("gap_repair")

    def missing_timestamp_set(timestamps, timeframe):
        normalized = pd.DatetimeIndex(
            pd.to_datetime(timestamps, utc=True).drop_duplicates().sort_values()
        )
        if normalized.empty:
            return set()
        expected = pd.date_range(normalized[0], normalized[-1], freq="15min")
        return set(expected.difference(normalized))

    fake_gap_repair.missing_timestamp_set = missing_timestamp_set
    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.setitem(sys.modules, "gap_repair", fake_gap_repair)
    monkeypatch.delitem(sys.modules, "gap_probe", raising=False)
    return importlib.import_module("gap_probe")


def observation(**overrides):
    value = {
        "raw_returned_count": 1,
        "raw_exact_present": False,
        "validated_exact_present": False,
        "raw_nearest_before_utc": None,
        "raw_nearest_after_utc": None,
        "request_error": None,
        "validation_error": None,
    }
    value.update(overrides)
    return value


def test_timestamps_from_raw_rows_ignores_malformed_values(monkeypatch):
    module = load_module(monkeypatch)
    timestamps = module.timestamps_from_raw_rows([
        [1767225600, 1, 1, 1, 1, 1],
        ["bad", 1, 1, 1, 1, 1],
        [],
        [1767226500, 1, 1, 1, 1, 1],
    ])
    assert timestamps.tolist() == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:15:00Z"),
    ]


def test_diagnose_exact_raw_row_reports_ohlc_failure(monkeypatch):
    module = load_module(monkeypatch)
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    rows = [[int(target.timestamp()), "10", "9", "8", "10", "5"]]
    diagnosed = module.diagnose_exact_raw_rows(rows, target)
    assert diagnosed[0]["validation_reasons"] == ["high_below_ohlc_max"]


def test_sample_missing_timestamps_spreads_samples(monkeypatch):
    module = load_module(monkeypatch)
    missing = {
        pd.Timestamp("2026-01-01T00:00:00Z")
        + pd.Timedelta(15 * int(i), unit="min")
        for i in range(5)
    }
    assert module.sample_missing_timestamps(missing, 3) == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:30:00Z"),
        pd.Timestamp("2026-01-01T01:00:00Z"),
    ]


def test_sample_missing_timestamps_rejects_zero(monkeypatch):
    module = load_module(monkeypatch)
    with pytest.raises(ValueError, match="at least 1"):
        module.sample_missing_timestamps([], 0)


def test_classify_validated_recoverable_takes_precedence(monkeypatch):
    module = load_module(monkeypatch)
    classification, recovered = module.classify_observations([
        observation(raw_exact_present=True, validated_exact_present=True),
    ])
    assert classification == "recoverable_validated"
    assert recovered is True


def test_classify_raw_present_but_rejected(monkeypatch):
    module = load_module(monkeypatch)
    classification, recovered = module.classify_observations([
        observation(raw_exact_present=True, validated_exact_present=False),
    ])
    assert classification == "present_but_rejected_by_validation"
    assert recovered is False


def test_classify_absent_when_raw_responses_bracket_target(monkeypatch):
    module = load_module(monkeypatch)
    classification, recovered = module.classify_observations([
        observation(raw_nearest_before_utc="2026-01-01T00:00:00+00:00"),
        observation(raw_nearest_after_utc="2026-01-01T00:30:00+00:00"),
    ])
    assert classification == "absent_from_raw_public_kline_response"
    assert recovered is False


def test_classify_all_failures_as_inconclusive(monkeypatch):
    module = load_module(monkeypatch)
    classification, recovered = module.classify_observations([
        observation(request_error="network"),
        observation(request_error="network"),
        observation(request_error="network"),
    ])
    assert classification == "inconclusive_api_failure"
    assert recovered is False


def test_probe_distinguishes_raw_exact_from_validated_exact(monkeypatch):
    module = load_module(monkeypatch)
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    calls = []

    def fetch_rows(symbol, timeframe, start):
        calls.append(pd.to_datetime(start, unit="s", utc=True))
        requested = pd.to_datetime(start, unit="s", utc=True)
        return [[int(requested.timestamp()), 10, 9, 8, 10, 5]]

    def convert_rows(rows, symbol, timeframe):
        requested = pd.to_datetime(rows[0][0], unit="s", utc=True)
        if requested == target:
            return pd.DataFrame({
                "timestamp": pd.Series(dtype="datetime64[ns, UTC]")
            })
        return pd.DataFrame({"timestamp": [requested]})

    result = module.probe_missing_timestamp(
        "btc_usdt",
        "minute15",
        target,
        fetch_rows=fetch_rows,
        convert_rows=convert_rows,
    )

    assert calls == [
        pd.Timestamp("2026-01-01T00:00:00Z"),
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T00:30:00Z"),
    ]
    assert result["classification"] == "present_but_rejected_by_validation"
    assert result["raw_exact_present"] is True
    assert result["validated_exact_present"] is False
    exact_observation = result["observations"][1]
    assert exact_observation["rejected_row_count"] == 1
    assert exact_observation["exact_raw_rows"][0]["validation_reasons"] == [
        "high_below_ohlc_max"
    ]


def test_probe_survives_partial_request_failure(monkeypatch):
    module = load_module(monkeypatch)
    target = pd.Timestamp("2026-01-01T00:15:00Z")
    call_count = 0

    def fetch_rows(symbol, timeframe, start):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("temporary")
        requested = pd.to_datetime(start, unit="s", utc=True)
        if requested == target:
            timestamps = [
                target - pd.Timedelta(15, unit="min"),
                target + pd.Timedelta(15, unit="min"),
            ]
        else:
            timestamps = [requested]
        return [
            [int(timestamp.timestamp()), 1, 1, 1, 1, 1]
            for timestamp in timestamps
        ]

    def convert_rows(rows, symbol, timeframe):
        return pd.DataFrame({
            "timestamp": pd.to_datetime(
                [row[0] for row in rows], unit="s", utc=True
            )
        })

    result = module.probe_missing_timestamp(
        "btc_usdt",
        "minute15",
        target,
        fetch_rows=fetch_rows,
        convert_rows=convert_rows,
    )
    assert result["failed_requests"] == 1
    assert result["successful_requests"] == 2
    assert result["classification"] == "absent_from_raw_public_kline_response"


def test_build_report_samples_only_series_with_gaps(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    for symbol in module.SYMBOLS:
        path = tmp_path / symbol / "minute15.parquet"
        path.parent.mkdir(parents=True)
        path.touch()

    frames = {
        "btc_usdt": pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:30:00Z",
            ])
        }),
        "eth_usdt": pd.DataFrame({
            "timestamp": pd.to_datetime([
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:15:00Z",
            ])
        }),
    }

    def frame_reader(path):
        return frames[path.parent.name]

    def probe_fn(symbol, timeframe, target, request_pause_seconds):
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "missing_timestamp_utc": target.isoformat(),
            "classification": "present_but_rejected_by_validation",
            "raw_exact_present": True,
            "validated_exact_present": False,
            "validated_recovered": False,
            "raw_bracketed_by_returned_candles": True,
            "successful_requests": 3,
            "failed_requests": 0,
            "validation_errors": 0,
            "observations": [],
        }

    report = module.build_probe_report(
        input_root=tmp_path,
        samples_per_series=1,
        request_pause_seconds=0,
        frame_reader=frame_reader,
        probe_fn=probe_fn,
    )
    assert report["summary"]["source_series_with_gaps"] == 1
    assert report["summary"]["raw_exact_targets"] == 1
    assert report["summary"]["validated_exact_targets"] == 0
    assert report["results"][0]["symbol"] == "btc_usdt"


def test_write_probe_report_creates_json_markdown_and_csv(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    report = {
        "generated_at_utc": "2026-08-03T00:00:00+00:00",
        "summary": {
            "source_series_with_gaps": 1,
            "sampled_series": 1,
            "sampled_missing_timestamps": 1,
            "total_source_missing_candles": 2,
            "successful_requests": 3,
            "failed_requests": 0,
            "validation_errors": 0,
            "raw_exact_targets": 1,
            "validated_exact_targets": 0,
            "classification_counts": {
                "present_but_rejected_by_validation": 1
            },
        },
        "results": [{
            "symbol": "btc_usdt",
            "timeframe": "minute15",
            "missing_timestamp_utc": "2026-01-01T00:15:00+00:00",
            "classification": "present_but_rejected_by_validation",
            "raw_exact_present": True,
            "validated_exact_present": False,
            "validated_recovered": False,
            "raw_bracketed_by_returned_candles": True,
            "successful_requests": 3,
            "failed_requests": 0,
            "validation_errors": 0,
            "source_rows": 2,
            "source_missing_candles": 1,
            "observations": [],
        }],
    }

    module.write_probe_report(report, tmp_path, clean=True)
    assert json.loads(
        (tmp_path / "_gap_probe.json").read_text()
    )["summary"] == report["summary"]
    assert "present_but_rejected" in (tmp_path / "_gap_probe.md").read_text()
    csv = pd.read_csv(tmp_path / "_gap_probe.csv")
    assert csv.loc[0, "symbol"] == "btc_usdt"
