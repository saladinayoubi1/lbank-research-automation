from datetime import datetime, timezone
import json

import pytest

import deepseek_provider as ds


def test_routine_routes_to_flash_non_thinking():
    decision = ds.route_task(complexity="routine")
    assert decision.model == "deepseek-v4-flash"
    assert decision.thinking is False
    assert decision.reasoning_effort is None


def test_complex_routes_to_flash_thinking():
    decision = ds.route_task(complexity="complex")
    assert decision.model == "deepseek-v4-flash"
    assert decision.thinking is True


def test_critical_routes_to_pro():
    decision = ds.route_task(complexity="critical")
    assert decision.model == "deepseek-v4-pro"
    assert decision.thinking is True


def test_unknown_complexity_rejected():
    with pytest.raises(ValueError):
        ds.route_task(complexity="mystery")


def test_cost_flash_cache_miss_and_output():
    usage = {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    assert ds.calculate_cost("deepseek-v4-flash", usage) == pytest.approx(0.42)


def test_cost_uses_cache_hit_when_reported():
    usage = {
        "prompt_tokens": 1_000_000,
        "prompt_cache_hit_tokens": 750_000,
        "prompt_cache_miss_tokens": 250_000,
        "completion_tokens": 0,
    }
    expected = 0.75 * 0.0028 + 0.25 * 0.14
    assert ds.calculate_cost("deepseek-v4-flash", usage) == pytest.approx(expected)


def test_unknown_model_pricing_fails_closed():
    with pytest.raises(ds.DeepSeekError):
        ds.calculate_cost("unknown", {})


def test_month_reset(tmp_path, monkeypatch):
    path = tmp_path / "usage.json"
    path.write_text(json.dumps({"month": "2000-01", "pricing_version": ds.PRICING_VERSION, "spent_usd": 4.9, "requests": 9}))
    ledger = ds.load_ledger(path)
    assert ledger["spent_usd"] == 0.0
    assert ledger["requests"] == 0


def test_stale_pricing_ledger_fails_closed(tmp_path):
    path = tmp_path / "usage.json"
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    path.write_text(json.dumps({"month": current_month, "pricing_version": "old", "spent_usd": 1.0, "requests": 1}))
    with pytest.raises(ds.DeepSeekError):
        ds.load_ledger(path)


def test_missing_key_fails_before_network(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(ds.DeepSeekError, match="missing"):
        ds.chat([{"role": "user", "content": "hi"}], ledger_path=tmp_path / "usage.json")


def test_exhausted_budget_fails_closed():
    ledger = {"spent_usd": ds.MONTHLY_BUDGET_USD}
    with pytest.raises(ds.BudgetExceeded):
        ds._check_preflight_budget(ledger, ds.DEFAULT_MODEL, 256)


def test_pro_reserve_is_protected():
    ledger = {"spent_usd": ds.MONTHLY_BUDGET_USD - ds.RESERVE_USD + 0.01}
    with pytest.raises(ds.BudgetExceeded):
        ds._check_preflight_budget(ledger, ds.PRO_MODEL, 256)


def test_max_tokens_bound():
    with pytest.raises(ds.DeepSeekError):
        ds._check_preflight_budget({"spent_usd": 0}, ds.DEFAULT_MODEL, 40000)
