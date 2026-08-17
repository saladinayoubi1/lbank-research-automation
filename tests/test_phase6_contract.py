from __future__ import annotations

import json
from pathlib import Path

CONTRACT = Path(".nexus/phase6-contract.json")


def test_phase6_is_new_bounded_contract_not_phase5_gate10():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["phase"] == 6
    assert contract["parent_issue"] == 591
    assert contract["phase5_reopened"] is False
    assert contract["gate10_created"] is False
    assert set(contract["gates"]) == {str(index) for index in range(7)}


def test_phase6_cannot_widen_financial_or_owner_authority():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["paper_only"] is True
    assert contract["live_trading_authority"] is False
    assert contract["private_exchange_credentials_allowed"] is False
    assert contract["withdrawals_allowed"] is False
    assert contract["production_promotion_allowed"] is False
    assert contract["billing_changes_allowed"] is False
    assert contract["signing_authority_allowed"] is False
    assert contract["deterministic_risk_final_authority"] is True
    assert contract["owner_boundary"]["self_authorized"] is False
    assert contract["paid_provider_smoke_required"] is False
