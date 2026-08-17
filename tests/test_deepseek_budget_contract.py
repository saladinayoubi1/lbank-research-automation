from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

import deepseek_provider as provider

ADR = Path("docs/architecture/ADR-AI-PROVIDER-BUDGET.md")


def test_budget_authority_is_bounded_and_versioned():
    assert provider.MONTHLY_BUDGET_USD == 5.00
    assert 0 < provider.RESERVE_USD < provider.MONTHLY_BUDGET_USD
    assert provider.PRICING_VERSION
    assert set(provider.PRICING) == provider.ALLOWED_MODELS


def test_unknown_or_alternate_accounting_authority_fails_closed():
    with pytest.raises(provider.DeepSeekError, match="alternate usage ledger"):
        provider._canonical_path("build/deepseek/alternate.json")

    ledger = provider._fresh_ledger()
    stale = deepcopy(ledger)
    stale["pricing_version"] = "stale"
    with pytest.raises(provider.DeepSeekError, match="pricing version"):
        provider._validate_ledger(stale)

    over = deepcopy(ledger)
    over["spent_usd"] = provider.MONTHLY_BUDGET_USD + 0.01
    with pytest.raises(provider.DeepSeekError, match="monthly cap"):
        provider._validate_ledger(over)


def test_reservation_total_must_match_inflight_state():
    ledger = provider._fresh_ledger()
    ledger["inflight"] = {
        "request": {
            "reserved_usd": 0.25,
            "model": provider.DEFAULT_MODEL,
            "pricing_version": provider.PRICING_VERSION,
            "status": "reserved",
        }
    }
    ledger["reserved_usd"] = 0.10
    with pytest.raises(provider.DeepSeekError, match="reservation total"):
        provider._validate_ledger(ledger)


def test_worst_case_reservation_accounts_for_input_and_full_output():
    small_tokens, small_cost = provider._worst_case_reservation(
        provider.DEFAULT_MODEL,
        [{"role": "user", "content": "x"}],
        16,
    )
    large_tokens, large_cost = provider._worst_case_reservation(
        provider.DEFAULT_MODEL,
        [{"role": "user", "content": "x" * 10_000}],
        4096,
    )
    assert large_tokens > small_tokens
    assert large_cost > small_cost > 0


def test_budget_adr_freezes_ambiguous_charge_and_recovery_semantics():
    text = ADR.read_text(encoding="utf-8")
    required = [
        "USD 5.00",
        "alternate ledger path is rejected",
        "retain/quarantine the reservation",
        "Do not assume zero cost",
        "month rollover",
        "kernel-managed exclusive lock",
        "No paid provider call is required",
        "The safe fallback is paid routing disabled",
        "Obsolescence triggers",
    ]
    for phrase in required:
        assert phrase in text
