from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pandas as pd


def load_module():
    fake_main = types.ModuleType("main")
    fake_main.OUTPUT_ROOT = Path("data/market")
    fake_main.SYMBOLS = ["btc_usdt"]
    fake_main.TIMEFRAMES = ["minute15"]
    fake_main.TIMEFRAME_SECONDS = {"minute15": 900, "hour1": 3600, "hour4": 14400}
    fake_main.get_klines = lambda *args, **kwargs: []
    fake_main.read_existing = lambda path: pd.DataFrame()
    fake_main.rows_to_frame = lambda rows, symbol, timeframe: pd.DataFrame()
    fake_main.save_merged = lambda existing, incoming, path: len(existing)
    fake_main.write_backfill_status = lambda: None
    sys.modules["main"] = fake_main
    sys.modules.pop("gap_repair", None)
    return importlib.import_module("gap_repair"), fake_main


def test_find_gap_starts_returns_first_missing_timestamp_per_gap():
    module, _ = load_module()
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


def test_missing_timestamp_set_lists_every_missing_candle():
    module, _ = load_module()
    timestamps = pd.Series(pd.to_datetime([
        "2026-01-01T00:00:00Z",
        "2026-01-01T00:45:00Z",
    ]))

    assert module.missing_timestamp_set(timestamps, "minute15") == {
        pd.Timestamp("2026-01-01T00:15:00Z").to_pydatetime(),
        pd.Timestamp("2026-01-01T00:30:00Z").to_pydatetime(),
    }


def test_select_missing_rows_does_not_append_non_gap_candles():
    module, _ = load_module()
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


def test_repair_series_skips_complete_series():
    module, fake_main = load_module()
    fake_main.read_existing = lambda path: pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:15:00Z",
        ])
    })
    module.read_existing = fake_main.read_existing
    called = False

    def get_klines(*args, **kwargs):
        nonlocal called
        called = True
        return []

    module.get_klines = get_klines

    assert module.repair_series("btc_usdt", "minute15") == 0
    assert called is False


def test_repair_series_merges_only_recovered_missing_rows():
    module, _ = load_module()
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

    assert module.repair_series("btc_usdt", "minute15") == 1
    assert captured["incoming"]["timestamp"].tolist() == [
        pd.Timestamp("2026-01-01T00:15:00Z")
    ]
