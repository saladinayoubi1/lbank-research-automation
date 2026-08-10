from __future__ import annotations

from pathlib import Path

import pytest

import deepseek_provider as ds


def _path(tmp_path: Path) -> Path:
    return tmp_path / "usage.json"


def test_large_input_small_output_reserves_input_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    messages = [{"role": "user", "content": "x" * 1_000_000}]
    _, amount = ds._worst_case_reservation(ds.DEFAULT_MODEL, messages, 1)
    assert amount > 0.13


def test_routine_cannot_consume_protected_reserve(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.4999
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.BudgetExceeded):
        ds._reserve(path, ds.DEFAULT_MODEL, [{"role": "user", "content": "hello"}], 1024, False)


def test_blocker_can_use_reserve_without_exceeding_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.60
    ds.save_ledger(path, ledger)
    rid, _ = ds._reserve(path, ds.PRO_MODEL, [{"role": "user", "content": "critical"}], 64, True)
    loaded = ds.load_ledger(path)
    assert rid in loaded["inflight"]
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_reservation_cannot_cross_routine_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["spent_usd"] = 4.49
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.BudgetExceeded):
        ds._reserve(path, ds.DEFAULT_MODEL, [{"role": "user", "content": "a" * 100000}], 1024, False)
    loaded = ds.load_ledger(path)
    assert loaded["spent_usd"] + loaded["reserved_usd"] <= ds.MONTHLY_BUDGET_USD


def test_missing_ledger_after_initialization_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = _path(tmp_path)
    ds.save_ledger(path, ds._fresh_ledger())
    path.unlink()
    with pytest.raises(ds.DeepSeekError, match="missing after prior initialization"):
        ds.load_ledger(path)


def test_inconsistent_usage_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    with pytest.raises(ds.DeepSeekError):
        ds.calculate_cost(ds.DEFAULT_MODEL, {
            "prompt_tokens": 10,
            "prompt_cache_hit_tokens": 8,
            "prompt_cache_miss_tokens": 8,
            "completion_tokens": 2,
        })


def test_month_rollover_with_inflight_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = _path(tmp_path)
    ledger = ds._fresh_ledger()
    ledger["month"] = "2000-01"
    ledger["inflight"] = {"x": {"reserved_usd": 0.1, "model": ds.DEFAULT_MODEL}}
    ledger["reserved_usd"] = 0.1
    ds.save_ledger(path, ledger)
    with pytest.raises(ds.DeepSeekError, match="rollover"):
        ds.load_ledger(path)


def test_successful_reconciliation_releases_reservation(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
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


def test_alternate_ledger_path_rejected_outside_tests(monkeypatch, tmp_path):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    with pytest.raises(ds.DeepSeekError, match="alternate usage ledger"):
        ds._canonical_or_test_path(tmp_path / "other.json")
