from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_validation_candidate_inventory as inv


def _candidate(task_id, decision):
    candidate = {
        "research_task_id": task_id,
        "decision": decision,
        "candidate_digest": task_id.split("-")[-1].zfill(64)[-64:],
    }
    verification = {
        "decision": "pass",
        "verification_digest": (task_id.split("-")[-1] + "f" * 64)[:64],
    }
    return candidate, verification


def test_inventory_preserves_every_decision_without_ranking(monkeypatch):
    mapping = {
        "P7-RESEARCH-COMPOSITE-015": "FORWARD_TO_VAL40",
        "P7-RESEARCH-COMPOSITE-016": "REJECTED_RESEARCH_VALIDATION",
        "P7-RESEARCH-COMPOSITE-017": "REJECTED_RESEARCH_VALIDATION",
    }

    def build(manager, receipt, report):
        candidate, _ = _candidate(manager["id"], mapping[manager["id"]])
        return candidate

    def verify(candidate):
        _, verification = _candidate(
            candidate["research_task_id"], candidate["decision"]
        )
        return verification

    monkeypatch.setattr(inv, "build_candidate", build)
    monkeypatch.setattr(inv, "verify_candidate", verify)
    entries = [
        {
            "manager_task": {"id": task_id},
            "producer_receipt": {"proof": task_id},
            "research_report": {"proof": task_id},
        }
        for task_id in mapping
    ]
    result = inv.build_inventory(entries)
    assert result["mission_order"] == list(mapping)
    assert result["forwarded_task_ids"] == ["P7-RESEARCH-COMPOSITE-015"]
    assert result["rejected_task_ids"] == [
        "P7-RESEARCH-COMPOSITE-016",
        "P7-RESEARCH-COMPOSITE-017",
    ]
    assert result["selection_basis"].startswith("no_ranking")
    assert result["qualification_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    assert inv.verify_inventory(result)["decision"] == "pass"


def test_inventory_rejects_duplicate_or_out_of_order_missions(monkeypatch):
    monkeypatch.setattr(
        inv,
        "build_candidate",
        lambda manager, *_: _candidate(
            manager["id"], "REJECTED_RESEARCH_VALIDATION"
        )[0],
    )
    monkeypatch.setattr(
        inv,
        "verify_candidate",
        lambda candidate: _candidate(
            candidate["research_task_id"], candidate["decision"]
        )[1],
    )
    row = lambda task_id: {
        "manager_task": {"id": task_id},
        "producer_receipt": {"proof": task_id},
        "research_report": {"proof": task_id},
    }
    with pytest.raises(inv.CompositeCandidateInventoryError, match="duplicated"):
        inv.build_inventory([row("P7-RESEARCH-COMPOSITE-015")] * 2)
    with pytest.raises(inv.CompositeCandidateInventoryError, match="mission order"):
        inv.build_inventory([
            row("P7-RESEARCH-COMPOSITE-017"),
            row("P7-RESEARCH-COMPOSITE-015"),
        ])


def test_inventory_verifier_rejects_redigested_manual_partition_tamper(monkeypatch):
    mapping = {
        "P7-RESEARCH-COMPOSITE-015": "FORWARD_TO_VAL40",
        "P7-RESEARCH-COMPOSITE-016": "REJECTED_RESEARCH_VALIDATION",
    }
    monkeypatch.setattr(
        inv,
        "build_candidate",
        lambda manager, *_: _candidate(manager["id"], mapping[manager["id"]])[0],
    )
    monkeypatch.setattr(
        inv,
        "verify_candidate",
        lambda candidate: _candidate(
            candidate["research_task_id"], candidate["decision"]
        )[1],
    )
    result = inv.build_inventory([
        {"manager_task":{"id":task_id},"producer_receipt":{"p":1},"research_report":{"p":1}}
        for task_id in mapping
    ])
    tampered = deepcopy(result)
    tampered["forwarded_task_ids"] = ["P7-RESEARCH-COMPOSITE-016"]
    tampered["rejected_task_ids"] = ["P7-RESEARCH-COMPOSITE-015"]
    core = dict(tampered)
    core.pop("inventory_digest", None)
    tampered["inventory_digest"] = inv.digest(core)
    assert inv.verify_inventory(tampered)["decision"] == "reject"


def test_inventory_grants_no_downstream_authority_when_empty():
    result = inv.build_inventory([])
    assert result["candidate_count"] == 0
    assert result["forwarded_task_ids"] == []
    assert result["rejected_task_ids"] == []
    assert result["candidate_state_created"] is False
    assert result["qualification_authority"] is False
    assert result["registry_mutation_authority"] is False
    assert result["promotion_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["automatic_strategy_promotion"] is False
    assert result["live_trading_authority"] is False
    assert inv.verify_inventory(result)["decision"] == "pass"
