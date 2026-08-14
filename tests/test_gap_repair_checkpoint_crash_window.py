from __future__ import annotations

import importlib
import sys
import tempfile
import types
from pathlib import Path

import pandas as pd
import pytest


def load_module(monkeypatch):
    fake_main = types.ModuleType("main")

    class LBankError(RuntimeError):
        pass

    fake_main.LBankError = LBankError
    fake_main.OUTPUT_ROOT = Path(tempfile.mkdtemp()) / "market"
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
    return importlib.import_module("gap_repair")


def gapped_frame():
    return pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
        ]),
        "symbol": ["btc_usdt", "btc_usdt"],
        "timeframe": ["minute15", "minute15"],
    })


def recovered_frame():
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01T00:15:00Z"]),
        "symbol": ["btc_usdt"],
        "timeframe": ["minute15"],
    })


def test_cursor_commit_failure_occurs_after_data_save_and_releases_owner(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda *args, **kwargs: recovered_frame()
    operations = []

    def save_merged(existing, incoming, path):
        operations.append("save_data")
        return len(existing) + 1

    def fail_cursor_commit(*args, **kwargs):
        operations.append("commit_cursor")
        raise OSError("simulated crash before durable cursor commit")

    module.save_merged = save_merged
    module._persist_next_index = fail_cursor_commit
    checkpoint = module._checkpoint_path("btc_usdt", "minute15")

    with pytest.raises(OSError, match="before durable cursor commit"):
        module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert operations == ["save_data", "commit_cursor"]
    assert Path(f"{checkpoint}.lock").exists()

    # The coordination file persists by design; ownership must still be reusable.
    with module.checkpoint_lock(checkpoint):
        pass


def test_failed_cursor_commit_does_not_report_recovery_complete(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda *args, **kwargs: recovered_frame()
    module.save_merged = lambda existing, incoming, path: len(existing) + 1
    module._persist_next_index = lambda *args, **kwargs: (_ for _ in ()).throw(
        OSError("cursor persistence unavailable")
    )

    with pytest.raises(OSError, match="cursor persistence unavailable"):
        module.repair_series_with_outcomes("btc_usdt", "minute15")
