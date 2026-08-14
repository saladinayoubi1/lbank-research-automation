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


def multi_gap_frame():
    return pd.DataFrame({
        "timestamp": pd.to_datetime([
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:30:00Z",
            "2026-01-01T01:00:00Z",
            "2026-01-01T01:30:00Z",
        ]),
        "symbol": ["btc_usdt"] * 4,
        "timeframe": ["minute15"] * 4,
    })


def recovered_frame():
    return pd.DataFrame({
        "timestamp": pd.to_datetime(["2026-01-01T00:15:00Z"]),
        "symbol": ["btc_usdt"],
        "timeframe": ["minute15"],
    })


def test_stale_lock_metadata_does_not_block_recovery(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    checkpoint = module._checkpoint_path("btc_usdt", "minute15")
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    Path(f"{checkpoint}.lock").write_text("dead-owner", encoding="utf-8")
    requested = []
    module.get_klines = lambda *args, **kwargs: requested.append(True) or []
    module.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])

    repaired, failures, outcomes = module.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    assert (repaired, failures) == (0, 0)
    assert requested == [True]
    assert [outcome.status for outcome in outcomes] == ["source_unavailable"]


def test_checkpoint_lock_file_persists_as_non_authoritative_coordination_inode(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    checkpoint = module._checkpoint_path("btc_usdt", "minute15")
    observed = []

    def get_klines(*args, **kwargs):
        lock = Path(f"{checkpoint}.lock")
        # On Windows, msvcrt.locking intentionally prevents another handle from
        # reading the locked byte range. Existence is the portable invariant;
        # file contents are coordination metadata, not ownership authority.
        observed.append(lock.exists())
        return []

    module.get_klines = get_klines
    module.rows_to_frame = lambda *args, **kwargs: pd.DataFrame(columns=["timestamp"])

    module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert observed == [True]
    assert Path(f"{checkpoint}.lock").exists()


def test_recovered_data_is_saved_before_cursor_commit(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda *args, **kwargs: recovered_frame()
    operations = []

    def save_merged(existing, incoming, path):
        operations.append("save_data")
        return len(existing) + 1

    def persist_cursor(*args, **kwargs):
        operations.append("commit_cursor")

    module.save_merged = save_merged
    module._persist_next_index = persist_cursor

    repaired, failures, _ = module.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    assert (repaired, failures) == (1, 0)
    assert operations == ["save_data", "commit_cursor"]


def test_data_save_failure_never_advances_cursor(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.read_existing = lambda path: gapped_frame()
    module.get_klines = lambda *args, **kwargs: [["unused"]]
    module.rows_to_frame = lambda *args, **kwargs: recovered_frame()
    cursor_commits = []

    def fail_save(existing, incoming, path):
        raise OSError("simulated durable data save failure")

    module.save_merged = fail_save
    module._persist_next_index = lambda *args, **kwargs: cursor_commits.append(True)

    checkpoint = module._checkpoint_path("btc_usdt", "minute15")
    with pytest.raises(OSError, match="durable data save failure"):
        module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert cursor_commits == []
    assert Path(f"{checkpoint}.lock").exists()


def test_bounded_cursor_survives_module_reload_and_rotates_next_gap(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    module.read_existing = lambda path: multi_gap_frame()
    first_requests = []
    module.get_klines = lambda symbol, timeframe, start: first_requests.append(start) or []

    module.repair_series_with_outcomes("btc_usdt", "minute15")
    assert len(first_requests) == 1

    reloaded = load_module(monkeypatch)
    reloaded.OUTPUT_ROOT = tmp_path
    reloaded.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    reloaded.read_existing = lambda path: multi_gap_frame()
    second_requests = []
    reloaded.get_klines = lambda symbol, timeframe, start: second_requests.append(start) or []

    reloaded.repair_series_with_outcomes("btc_usdt", "minute15")

    assert len(second_requests) == 1
    assert second_requests[0] != first_requests[0]


def test_fixed_gap_set_is_exhaustively_traversed_across_clean_restarts(monkeypatch, tmp_path):
    requested = []
    for _ in range(3):
        module = load_module(monkeypatch)
        module.OUTPUT_ROOT = tmp_path
        module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
        module.read_existing = lambda path: multi_gap_frame()
        module.get_klines = lambda symbol, timeframe, start: requested.append(start) or []
        module.repair_series_with_outcomes("btc_usdt", "minute15")

    assert len(requested) == 3
    assert len(set(requested)) == 3


def test_gap_set_change_fails_closed_before_network(monkeypatch, tmp_path):
    module = load_module(monkeypatch)
    module.OUTPUT_ROOT = tmp_path
    module.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    module.read_existing = lambda path: multi_gap_frame()
    module.get_klines = lambda *args, **kwargs: []
    module.repair_series_with_outcomes("btc_usdt", "minute15")

    changed = load_module(monkeypatch)
    changed.OUTPUT_ROOT = tmp_path
    changed.MAX_GAP_WINDOWS_PER_SERIES_PER_RUN = 1
    changed.read_existing = lambda path: gapped_frame()
    requested = []
    changed.get_klines = lambda *args, **kwargs: requested.append(True) or []

    repaired, failures, outcomes = changed.repair_series_with_outcomes(
        "btc_usdt", "minute15"
    )

    assert (repaired, failures) == (0, 0)
    assert requested == []
    assert [outcome.status for outcome in outcomes] == ["checkpoint_invalid"]
