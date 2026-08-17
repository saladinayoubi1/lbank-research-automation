from __future__ import annotations

import json
from pathlib import Path

CONTRACT = Path(".nexus/phase6-contract.json")
CHECKPOINT = Path(".nexus/phase6-checkpoint.json")
PHASE5 = Path(".nexus/phase5-checkpoint.json")
ADR = Path("docs/architecture/ADR-AI-PROVIDER-BUDGET.md")
PIPELINE = Path("phase6_research_pipeline.py")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_phase6_candidate_checkpoint_closes_all_bounded_engineering_gates():
    contract = load(CONTRACT)
    checkpoint = load(CHECKPOINT)
    assert contract["status"] == "candidate_complete"
    assert contract["engineering_gates_complete"] is True
    assert contract["completed_gates"] == [str(index) for index in range(7)]
    assert checkpoint["formal_gates"] == "0-6"
    assert checkpoint["formal_gates_complete"] is True
    assert checkpoint["remaining_non_owner_engineering_tasks"] == []
    assert checkpoint["final_pr"] == 592
    assert checkpoint["parent_issue"] == 591


def test_closure_preserves_phase5_and_never_widens_authority():
    contract = load(CONTRACT)
    checkpoint = load(CHECKPOINT)
    phase5 = load(PHASE5)
    for artifact in (contract, checkpoint):
        assert artifact["paper_only"] is True
        assert artifact["live_trading_authority"] is False
        assert artifact["private_exchange_credentials_allowed"] is False
        assert artifact["withdrawals_allowed"] is False
        assert artifact["production_promotion_allowed"] is False
        assert artifact["billing_changes_allowed"] is False
        assert artifact["signing_authority_allowed"] is False
        assert artifact["deterministic_risk_final_authority"] is True
        assert artifact["profitability_claim"] is False
        assert artifact["phase5_reopened"] is False
        assert artifact["gate10_created"] is False
    assert phase5["phase"] == 5
    assert phase5["formal_gates_complete"] is True
    assert checkpoint["phase5_checkpoint"] == PHASE5.as_posix()


def test_only_remaining_boundary_is_explicitly_owner_only_and_nonblocking():
    contract = load(CONTRACT)
    checkpoint = load(CHECKPOINT)
    assert contract["owner_boundary"] == {
        "issue": 568,
        "action": "Gate 4 frozen control-plane re-authoritative promotion",
        "self_authorized": False,
        "phase6_blocking": False,
    }
    boundary = checkpoint["owner_only_optional_boundary"]
    assert boundary["issue"] == 568
    assert boundary["required_for_current_project_closure"] is False


def test_required_final_artifacts_exist_and_paid_smoke_is_not_completion_authority():
    checkpoint = load(CHECKPOINT)
    assert PIPELINE.is_file()
    assert ADR.is_file()
    assert checkpoint["canonical_research_pipeline"] == PIPELINE.as_posix()
    assert checkpoint["deepseek_budget_adr"] == ADR.as_posix()
    assert checkpoint["paid_provider_smoke_required"] is False
    assert checkpoint["deepseek_issue"]["hard_cap_code_integrated_before_phase6"] is True
    assert checkpoint["deepseek_issue"]["phase6_added_adr_and_offline_contract_tests"] is True
