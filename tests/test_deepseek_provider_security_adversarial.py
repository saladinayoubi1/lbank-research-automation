from __future__ import annotations

import json

import pytest

import deepseek_provider as dp


def _ledger() -> dict:
    return {
        "schema_version": dp.LEDGER_SCHEMA,
        "month": dp._month_key(),
        "pricing_version": dp.PRICING_VERSION,
        "spent_usd": 1.0,
        "reserved_usd": 0.0,
        "requests": 1,
        "inflight": {},
    }


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize("field", ["spent_usd", "reserved_usd"])
def test_non_finite_top_level_budget_values_fail_closed(field, value):
    ledger = _ledger()
    ledger[field] = value
    with pytest.raises(dp.DeepSeekError, match="accounting is malformed"):
        dp._validate_ledger(ledger)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_inflight_reservation_fails_closed(value):
    ledger = _ledger()
    ledger["reserved_usd"] = value if value != float("-inf") else 0.0
    ledger["inflight"] = {
        "attacker-controlled-request": {
            "reserved_usd": value,
            "model": dp.DEFAULT_MODEL,
            "pricing_version": dp.PRICING_VERSION,
            "created_at": "2026-08-17T06:00:00+00:00",
            "status": "reserved",
        }
    }
    with pytest.raises(dp.DeepSeekError):
        dp._validate_ledger(ledger)


@pytest.mark.parametrize("field", ["spent_usd", "reserved_usd"])
def test_boolean_budget_values_are_not_accepted_as_numbers(field):
    ledger = _ledger()
    ledger[field] = True
    with pytest.raises(dp.DeepSeekError, match="accounting is malformed"):
        dp._validate_ledger(ledger)


def test_boolean_request_count_is_rejected():
    ledger = _ledger()
    ledger["requests"] = True
    with pytest.raises(dp.DeepSeekError, match="request count is malformed"):
        dp._validate_ledger(ledger)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_non_standard_json_constants_cannot_reset_or_bypass_budget(tmp_path, literal):
    path = tmp_path / "usage.json"
    payload = _ledger()
    encoded = json.dumps(payload).replace("1.0", literal, 1)
    path.write_text(encoded, encoding="utf-8")
    with pytest.raises(dp.DeepSeekError):
        dp.load_ledger(path)


def test_valid_finite_budget_ledger_still_passes():
    ledger = _ledger()
    assert dp._validate_ledger(ledger) is ledger
