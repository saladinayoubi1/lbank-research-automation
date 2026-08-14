from __future__ import annotations

import importlib
import sys
import tempfile
import types
from pathlib import Path

import pandas as pd


def load_module(monkeypatch):
    fake_main = types.ModuleType("main")

    class LBankError(RuntimeError):
        pass

    fake_main.LBankError = LBankError
    fake_main.OUTPUT_ROOT = Path(tempfile.mkdtemp()) / "market"
    fake_main.SYMBOLS = ["btc_usdt"]
    fake_main.TIMEFRAMES = ["minute15"]
    fake_main.TIMEFRAME_SECONDS = {"minute15": 900}
    fake_main.get_klines = lambda *args, **kwargs: []
    fake_main.read_existing = lambda path: pd.DataFrame()
    fake_main.rows_to_frame = lambda rows, symbol, timeframe: pd.DataFrame()
    fake_main.save_merged = lambda existing, incoming, path: len(existing)
    fake_main.write_backfill_status = lambda: None

    monkeypatch.setitem(sys.modules, "main", fake_main)
    monkeypatch.delitem(sys.modules, "gap_repair", raising=False)
    return importlib.import_module("gap_repair")


def frame(timestamps):
    values = pd.to_datetime(timestamps)
    return pd.DataFrame(
        {
            "timestamp": values,
            "symbol": ["btc_usdt"] * len(values),
            "timeframe": ["minute15"] * len(values),
        }
    )


def test_successful_repair_rebinds_checkpoint_to_post_save_gap_set(monkeypatch, tmp_path):
    before = frame(
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:30:00Z",
        ]
    )
    after = frame(
        [
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:15:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:30:00Z",
        ]
    )
    recovered = frame(["2026-01-01T00:15:00Z"])
    saved = {"done": False}

    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    module.read_existing = lambda path: after if saved["done"] else before
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda *args, **kwargs: recovered

    def save_merged(existing, incoming, path):
        saved["done"] = True
        return len(existing) + 1

    module.save_merged = save_merged
    repaired, failures, outcomes = module.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    assert (repaired, failures) == (1, 0)
    assert outcomes[0].status == "recovered"

    reloaded = load_module(monkeypatch)
    reloaded.OUTPUT_ROOT = tmp_path
    reloaded.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    reloaded.read_existing = lambda path: after
    requested = []
    reloaded.get_klines = (
        lambda symbol, timeframe, start: requested.append(start) or []
    )

    repaired, failures, outcomes = reloaded.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    assert (repaired, failures) == (0, 0)
    assert requested == [int(pd.Timestamp("2026-01-01T00:45:00Z").timestamp())]
    assert outcomes[0].status == "source_unavailable"
