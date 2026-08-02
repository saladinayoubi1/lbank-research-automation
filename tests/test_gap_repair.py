from __future__ import annotations

import importlib
import sys
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
    fake_main.OUTPUT_ROOT = Path("data/market")
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

    assert selected["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01T00:30:00Z")
    ]


def test_repair_series_skips_complete_series(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.read_existing = lambda path: pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:15:00Z",
        ])
    })
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
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
        ]),
        "symbol": ["btc_usdt", "btc_usdt"],
        "timeframe": ["minute15", "minute15"],
    })
    api_frame = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T00:45:00Z",
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

    assert module.repair_series("btc_usdt", "minute15") == (1, 0)
    assert captured["incoming"]["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01T00:15:00Z")
    ]


def test_request_budget_skips_gap_starts_already_recovered(monkeypatch):
    module, _ = load_module(monkeypatch)
    existing = pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:30:00Z",
            "2026-01-01T02:00:00Z",
        ]),
        "symbol": ["btc_usdt"] * 5,
        "timeframe": ["minute15"] * 5,
    })
    calls: list[pd.Timestamp] = []

    module.read_existing = lambda path: existing

    def get_klines(symbol, timeframe, start):
        calls.append(pd.to_datetime(start, unit="s", utc=True))
        return [["unused"]]

    module.get_klines = get_klines

    def rows_to_frame(rows, symbol, timeframe):
        start = calls[-1]
        timestamps = [start]
        if start == pd.Timestamp("2026-01-01T00:15:00Z"):
            timestamps.append(pd.Timestamp("2026-01-01T00:45:00Z"))
        return pd.DataFrame({
            "timestamp": timestamps,
            "symbol": [symbol] * len(timestamps),
            "timeframe": [timeframe] * len(timestamps),
        })

    module.rows_to_frame = rows_to_frame
    module.save_merged = (
        lambda current, incoming, path:
        len(current) + len(pd.concat(incoming, ignore_index=True))
    )

    assert module.repair_series("btc_usdt", "minute15") == (4, 0)
    assert calls == [
        pd.Timestamp("2026-01-01T00:15:00Z"),
        pd.Timestamp("2026-01-01T01:15:00Z"),
        pd.Timestamp("2026-01-01T01:45:00Z"),
    ]


def test_repair_series_counts_api_failures_without_aborting_series(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.read_existing = lambda path: pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:30:00Z",
        ])
    })

    def get_klines(*args, **kwargs):
        raise requests.RequestException("temporary failure")

    module.get_klines = get_klines

    assert module.repair_series("btc_usdt", "minute15") == (0, 3)


def test_repair_all_stops_after_failure_limit_and_writes_status(monkeypatch):
    module, _ = load_module(monkeypatch)
    module.SYMBOLS = ["btc_usdt", "eth_usdt", "aero_usdt"]
    module.TIMEFRAMES = ["minute15"]
    calls = []
    status_calls = []

    def repair_series(symbol, timeframe):
        calls.append((symbol, timeframe))
        return 0, 1

    module.repair_series = repair_series
    module.write_backfill_status = lambda: status_calls.append(True)

    with pytest.raises(RuntimeError, match="3 failed API request windows"):
        module.repair_all()

    assert calls == [
        ("btc_usdt", "minute15"),
        ("eth_usdt", "minute15"),
        ("aero_usdt", "minute15"),
    ]
    assert status_calls == [True]
