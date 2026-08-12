from __future__ import annotations

import importlib
import sys
import tempfile
import types
from pathlib import Path

import pandas as pd
import pytest
import requests


def load_module(monkeypatch):
    fake_main = types.ModuleType("main")

    class LBankError(RuntimeError):
        pass

    fake_main.LBankError = LBankError
    # macOS may return a tempfile path through the system /var -> /private/var
    # alias. Resolve only the test fixture root so production symlink defenses
    # remain strict while the fixture uses the canonical path.
    fake_main.OUTPUT_ROOT = Path(tempfile.mkdtemp()).resolve() / "market"
    fake_main.SYMBOLS = ["btc_usdt"]
    fake_main.TIMEFRAMES = ["minute15"]
    fake_main.TIMEFRAME_SECONDS = {
        "minute15": 900,
        "hour1": 3600,
        "hour4": 14400,
    }
    fake_main.get_klines = lambda *args, **kwargs: []
    fake_main.read_existing = lambda path: pd.DataFrame()
    fake_main.rows_to_frame = lambda rows, symbol, timeframe: pd.DataFrame()
    fake_main.save_merged = lambda existing, incoming, path: len(existing)
    fake_main.write_backfill_status = lambda: None

    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.delitem(sys.modules, "gap_repair", raising=False)
    return importlib.import_module("gap_repair"), fake_main


def test_find_gap_starts_returns_first_missing_timestamp_per_gap(monkeypatch):
    module, _ = load_module(monkeypatch)
    timestamps = pd.Series(pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:15:00Z",
        "2026-01-01T00:45:00Z",
        "2026-01-01T01:30:00Z",
    ]))

    assert module.find_gap_starts(timestamps, "minute15") == [
        pd.Timestamp("2026-01-01T00:30:00Z"),
        pd.Timestamp("2026-01-01T01:00:00Z"),
    ]


def test_missing_timestamp_set_lists_every_missing_candle(monkeypatch):
    module, _ = load_module(monkeypatch)
    timestamps = pd.Series(pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:45:00Z",
    ]))

    assert module.missing_timestamp_set(timestamps, "minute15") == {
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T00:30:00Z"),
    }


def test_select_missing_rows_does_not_append_non_gap_candles(monkeypatch):
    module, _ = load_module(monkeypatch)
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:45:00Z",
        ]),
        "close": [1, 2, 3],
    })
    missing = {pd.Timestamp("2026-01-01T00:30:00Z")}
    selected = module.select_missing_rows(frame, missing)
    assert selected["timestamp"].tolist() == [pd.Timestamp("2026-01-01T00:30:00Z")]


def test_repair_series_skips_complete_series(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.read_existing = lambda path: pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"
    ])})
    called = False

    def get_klines(*args, **kwargs):
        nonlocal called
        called = True
        return []

    module.get_klines = get_klines
    assert module.repair_series("btc_usdt", "minute15") == (0, 0)
    assert called is False


def test_repair_series_merges_only_recovered_missing_rows(monkeypatch):
    module, _ = load_module(monkeypatch)
    existing = pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"]),
        "symbol": ["btc_usdt", "btc_usdt"],
        "timeframe": ["minute15", "minute15"],
    })
    api_frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:15:00Z", "2026-01-01T00:30:00Z", "2026-01-01T00:45:00Z"
        ]),
        "symbol": ["btc_usdt"] * 3,
        "timeframe": ["minute15"] * 3,
    })
    captured = {}
    module.read_existing = lambda path: existing
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda rows, symbol, timeframe: api_frame

    def save_merged(current, incoming, path):
        captured["incoming"] = pd.concat(incoming, ignore_index=True)
        return len(current) + len(captured["incoming"])

    module.save_merged = save_merged
    repaired, failures, outcomes = module.repair_series_with_outcomes("btc_usdt", "minute15")
    assert (repaired, failures) == (1, 0)
    assert outcomes[0].status == "recovered"
    assert outcomes[0].recovered_candles == 1
    assert captured["incoming"]["timestamp"].tolist() == [pd.Timestamp("2026-01-01T00:15:00Z")]


def test_successful_empty_response_is_source_unavailable(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.read_existing = lambda path: pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"
    ])})
    module.get_klines = lambda *args, **kwargs: []
    module.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])
    repaired, failures, outcomes = module.repair_series_with_outcomes("btc_usdt", "minute15")
    assert (repaired, failures) == (0, 0)
    assert [outcome.status for outcome in outcomes] == ["source_unavailable"]


def test_api_exception_is_fetch_failed(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.read_existing = lambda path: pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"
    ])})

    def get_klines(*args, **kwargs):
        raise requests.RequestException("temporary failure")

    module.get_klines = get_klines
    repaired, failures, outcomes = module.repair_series_with_outcomes("btc_usdt", "minute15")
    assert (repaired, failures) == (0, 1)
    assert [outcome.status for outcome in outcomes] == ["fetch_failed"]
    assert outcomes[0].detail == "RequestException"


def test_request_budget_records_deferred_windows(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    module.read_existing = lambda path: pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z", "2026-01-01T01:00:00Z"
    ])})
    module.get_klines = lambda *args, **kwargs: []
    module.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])
    _, _, outcomes = module.repair_series_with_outcomes("btc_usdt", "minute15")
    assert [outcome.status for outcome in outcomes] == ["source_unavailable", "deferred_budget"]


def test_request_budget_rotates_to_later_gap_on_next_round(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    existing = pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:30:00Z",
        "2026-01-01T01:00:00Z",
    ])})
    module.read_existing = lambda path: existing
    requested = []

    def get_klines(symbol, timeframe, start):
        requested.append(pd.to_datetime(start, unit="s", utc=True))
        return []

    module.get_klines = get_klines
    module.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])

    module.repair_series_with_outcomes("btc_usdt", "minute15")
    module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert requested == [
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T00:45:00Z"),
    ]


def test_persisted_cursor_survives_module_restart(monkeypatch, tmp_path):
    existing = pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:30:00Z",
        "2026-01-01T01:00:00Z",
    ])})
    requested = []

    first, _ = load_module(monkeypatch)
    first.OUTPUT_ROOT = tmp_path
    first.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    first.read_existing = lambda path: existing
    first.get_klines = lambda symbol, timeframe, start: requested.append(pd.to_datetime(start, unit="s", utc=True)) or []
    first.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])
    first.repair_series_with_outcomes("btc_usdt", "minute15")

    second, _ = load_module(monkeypatch)
    second.OUTPUT_ROOT = tmp_path
    second.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    second.read_existing = lambda path: existing
    second.get_klines = lambda symbol, timeframe, start: requested.append(pd.to_datetime(start, unit="s", utc=True)) or []
    second.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])
    second.repair_series_with_outcomes("btc_usdt", "minute15")

    assert requested == [
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T00:45:00Z"),
    ]


def test_corrupt_persisted_cursor_fails_closed(monkeypatch, tmp_path):
    module, _ = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00:00Z", "2026-01-01T00:30:00Z"
    ])})
    checkpoint = tmp_path / "_gap_repair_checkpoints" / "btc_usdt" / "minute15.json"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_text("{broken", encoding="utf-8")
    requested = []
    module.get_klines = lambda *args, **kwargs: requested.append(True) or []

    repaired, failures, outcomes = module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert (repaired, failures) == (0, 0)
    assert requested == []
    assert [outcome.status for outcome in outcomes] == ["checkpoint_invalid"]


def test_write_gap_repair_report_distinguishes_failure_classes(monkeypatch, tmp_path):
    module, _ = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    outcomes = [
        module.GapRepairOutcome("btc_usdt", "minute15", "2026-01-01T00:15:00+00:00", "source_unavailable", 0, "no candle"),
        module.GapRepairOutcome("eth_usdt", "hour1", "2026-01-01T01:00:00+00:00", "fetch_failed", 0, "RequestException"),
    ]
    module.write_gap_repair_report(outcomes)
    report = pd.read_csv(tmp_path / "_gap_repair_status.csv")
    assert set(report["status"]) == {"source_unavailable", "fetch_failed"}
    markdown = (tmp_path / "_gap_repair_status.md").read_text(encoding="utf-8")
    assert "source_unavailable" in markdown
    assert "fetch_failed" in markdown


def test_repair_all_stops_after_failure_limit_and_writes_reports(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.SYMBOLS = ["btc_usdt", "eth_usdt", "aero_usdt"]
    module.TIMEFRAMES = ["minute15"]
    calls = []
    status_calls = []
    report_calls = []

    def repair_series_with_outcomes(symbol, timeframe):
        calls.append((symbol, timeframe))
        outcome = module.GapRepairOutcome(symbol, timeframe, "2026-01-01T00:15:00+00:00", "fetch_failed", 0, "RequestException")
        return 0, 1, [outcome]

    module.repair_series_with_outcomes = repair_series_with_outcomes
    module.write_gap_repair_report = lambda outcomes: report_calls.append(outcomes)
    module.write_backfill_status = lambda: status_calls.append(True)
    with pytest.raises(RuntimeError, match="3 failed API request windows"):
        module.repair_all()
    assert calls == [("btc_usdt", "minute15"), ("eth_usdt", "minute15"), ("aero_usdt", "minute15")]
    assert len(report_calls[0]) == 3
    assert status_calls == [True]
