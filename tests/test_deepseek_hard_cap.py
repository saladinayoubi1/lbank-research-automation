from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

import deepseek_provider as ds


def _path(tmp_path: Path) -> Path:
    return tmp_path / "usage.json"


def test_large_input_small_output_reserves_input_cost(tmp_path, monkeypatch):
    messages = [{"role": "user", "content": "x" * 1_000_000}]
    _, amount = ds._worst_case_reservation(ds.DEFAULT_MODEL, messages, 1)
    assert amount > 0.13


def test_routine_cannot_consume_protected_reserve(tmp_path, monkeypatch):
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.4999
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.BudgetExceeded):
        ds._reserve(path, ds.DEFAULT_MODEL, [{"role": "user", "content": "hello"}], 1024, False)


def test_blocker_can_use_reserve_without_exceeding_cap(tmp_path, monkeypatch):
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.60
    ds.save_ledger(path, ledger)
    rid, _ = ds._reserve(path, ds.PRO_MODEL, [{"role": "user", "content": "critical"}], 64, True)
    loaded = ds.load_ledger(path)
    assert rid in loaded["inflight"]
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_reservation_cannot_cross_routine_cap(tmp_path, monkeypatch):
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.49
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.BudgetExceeded):
        ds._reserve(path, ds.DEFAULT_MODEL, [{"role": "user", "content": "a" * 100000}], 1024, False)
    loaded = ds.load_ledger(path)
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_concurrent_last_slice_allows_only_one_reservation(tmp_path):
    path = _path(tmp_path)
    messages = [{"role": "user", "content": "critical"}]
    _, amount = ds._worst_case_reservation(ds.PRO_MODEL, messages, 64)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = ds.MONTHLY_BUDGET_USD - (amount * 1.5)
    ds.save_ledger(path, ledger)

    barrier = threading.Barrier(2)

    def reserve_once():
        barrier.wait()
        try:
            rid, _ = ds._reserve(path, ds.PRO_MODEL, messages, 64, True)
            return ("reserved", rid)
        except ds.BudgetExceeded:
            return ("rejected", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _n: reserve_once(), range(2)))

    assert sorted(result[0] for result in results) == ["rejected", "reserved"]
    loaded = ds.load_ledger(path)
    assert len(loaded["inflight"]) == 1
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_ambiguous_timeout_retains_reservation_and_reduces_remaining_budget(tmp_path, monkeypatch):
    path = _path(tmp_path)
    monkeypatch.setattr(ds, "CANONICAL_LEDGER", path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-key")

    def timeout(*_args, **_kwargs):
        raise TimeoutError("simulated ambiguous timeout")

    monkeypatch.setattr(ds.request, "urlopen", timeout)
    before = ds.remaining_budget(ds._fresh_ledger())

    with pytest.raises(ds.AmbiguousCharge, match="ambiguous"):
        ds.chat(
            [{"role": "user", "content": "Reply with exactly: NEXUS_DEEPSEEK_OK"}],
            blocker=True,
            max_tokens=64,
            ledger_path=path,
            timeout=0.01,
        )

    loaded = ds.load_ledger(path)
    assert len(loaded["inflight"]) == 1
    assert loaded["reserved_usd"] > 0
    assert ds.remaining_budget(loaded) < before
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_missing_ledger_after_initialization_fails_closed(tmp_path, monkeypatch):
    path = _path(tmp_path)
    ds.save_ledger(path, ds._fresh_ledger())
    path.unlink()
    with pytest.raises(ds.DeepSeekError, match="missing after prior initialization"):
        ds.load_ledger(path)


def test_inconsistent_usage_rejected(tmp_path, monkeypatch):
    with pytest.raises(ds.DeepSeekError):
        ds.calculate_cost(ds.DEFAULT_MODEL, {
            "prompt_tokens": 10,
            "prompt_cache_hit_tokens": 8,
            "prompt_cache_miss_tokens": 8,
            "completion_tokens": 2,
        })


def test_month_rollover_with_inflight_fails_closed(tmp_path, monkeypatch):
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["month"] = "2000-01"
    ledger["inflight"] = {"x": {"reserved_usd": 0.1, "model": ds.DEFAULT_MODEL}}
    ledger["reserved_usd"] = 0.1
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.DeepSeekError, match="rollover"):
        ds.load_ledger(path)


def test_successful_reconciliation_releases_reservation(tmp_path, monkeypatch):
    path = _path(tmp_path)
    rid, _ = ds._reserve(path, ds.DEFAULT_MODEL, [{"role": "user", "content": "hello"}], 32, False)
    actual, ledger = ds._reconcile(path, rid, ds.DEFAULT_MODEL, {
        "prompt_tokens": 5,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 5,
        "completion_tokens": 2,
    })
    assert actual > 0
    assert ledger["reserved_usd"] == 0
    assert rid not in ledger["inflight"]


def test_alternate_ledger_path_rejected_even_if_pytest_env_is_forged(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "forged")
    with pytest.raises(ds.DeepSeekError, match="alternate usage ledger"):
        ds._canonical_path(tmp_path / "other.json")


def test_save_ledger_fsyncs_before_replace(monkeypatch, tmp_path):
    path = _path(tmp_path)
    events = []
    real_fsync = ds.os.fsync
    real_replace = ds.os.replace

    def tracked_fsync(fd):
        events.append("fsync")
        return real_fsync(fd)

    def tracked_replace(src, dst):
        events.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(ds.os, "fsync", tracked_fsync)
    monkeypatch.setattr(ds.os, "replace", tracked_replace)
    ds.save_ledger(path, ds._fresh_ledger())

    assert "replace" in events
    assert "fsync" in events
    assert events.index("fsync") < events.index("replace")


def test_save_ledger_fsync_failure_fails_closed(monkeypatch, tmp_path):
    path = _path(tmp_path)

    def fail_fsync(_fd):
        raise OSError("simulated durability failure")

    monkeypatch.setattr(ds.os, "fsync", fail_fsync)
    with pytest.raises(ds.DeepSeekError, match="durability commit failed"):
        ds.save_ledger(path, ds._fresh_ledger())
