from datetime import datetime, timezone
import json

import pytest

import deepseek_provider as ds


def test_routine_routes_to_flash_non_thinking():
    decision = ds.route_task(complexity="routine")
    assert decision.model == ds.DEFAULT_MODEL
    assert decision.thinking is False
    assert decision.reasoning_effort is None


def test_complex_routes_to_flash_thinking():
    decision = ds.route_task(complexity="complex")
    assert decision.model == ds.DEFAULT_MODEL
    assert decision.thinking is True


def test_critical_routes_to_pro():
    decision = ds.route_task(complexity="critical")
    assert decision.model == ds.PRO_MODEL
    assert decision.thinking is True


def test_unknown_complexity_rejected():
    with pytest.raises(ValueError):
        ds.route_task(complexity="mystery")


def test_cost_flash_cache_miss_and_output():
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 1_000_000,
        "completion_tokens": 1_000_000,
    }
    assert ds.calculate_cost(ds.DEFAULT_MODEL, usage) == pytest.approx(0.42)


def test_cost_uses_cache_hit_when_reported():
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_cache_hit_tokens": 750_000,
        "prompt_cache_miss_tokens": 250_000,
        "completion_tokens": 0,
    }
    expected = 0.75 * 0.0028 + 0.25 * 0.14
    assert ds.calculate_cost(ds.DEFAULT_MODEL, usage) == pytest.approx(expected)


def test_unknown_model_pricing_fails_closed():
    with pytest.raises(ds.DeepSeekError):
        ds.calculate_cost("unknown", {"prompt_tokens": 0, "completion_tokens": 0})


def test_month_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = tmp_path / "usage.json"
    ledger = ds._fresh_ledger()
    ledger["month"] = "2000-01"
    ledger["spent_usd"] = 4.9
    ledger["requests"] = 9
    ds.save_ledger(path, ledger)
    reset = ds.load_ledger(path)
    assert reset["spent_usd"] == 0.0
    assert reset["requests"] == 0


def test_stale_pricing_ledger_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    path = tmp_path / "usage.json"
    ledger = ds._fresh_ledger()
    ledger["pricing_version"] = "old"
    path.write_text(json.dumps(ledger))
    with pytest.raises(ds.DeepSeekError):
        ds.load_ledger(path)


def test_missing_key_fails_before_network(monkeypatch, tmp_path):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ds.DeepSeekError, match="missing"):
        ds.chat([{"role": "user", "content": "hi"}], ledger_path=tmp_path / "usage.json")


def test_max_tokens_bound():
    with pytest.raises(ds.DeepSeekError):
        ds._worst_case_reservation(ds.DEFAULT_MODEL, [{"role": "user", "content": "x"}], 40000)
