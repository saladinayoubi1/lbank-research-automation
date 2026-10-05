from __future__ import annotations

from copy import deepcopy

import pytest

from nexus_strategy_independent_qa import digest
from nexus_strategy_qualification_gate import (
    StrategyQualificationError,
    evaluate_qualification,
    verify_qualification,
)
from nexus_strategy_review_qa_handoff import qa_task_id


def _handoff():
    core = {
        "schema_version": "nexus.strategy-review-qa-task.v1",
        "id": qa_task_id("a" * 64, "b" * 40, "d" * 64),
        "task_kind": "strategy_review_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "source_sha": "b" * 40,
        "proposal_digest": "a" * 64,
        "proposal_result_digest": "c" * 64,
        "requalification_digest": "d" * 64,
        "requalification_verification_digest": "e" * 64,
        "family": "momentum",
        "timeframe": "hour4",
        "variant_id": "v1",
        "strategy_config": {"lookback": 16},
        "strategy_config_digest": "",
        "runtime_evidence": [
            {
                "symbol": "BTCUSDT",
                "dataset_binding_sha256": "f" * 64,
                "pipeline_digest": "1" * 64,
                "qualification_digest": "2" * 64,
                "last_open_time_ms": 1_800_000_000_000,
            },
            {
                "symbol": "ETHUSDT",
                "dataset_binding_sha256": "3" * 64,
                "pipeline_digest": "4" * 64,
                "qualification_digest": "5" * 64,
                "last_open_time_ms": 1_800_000_000_000,
            },
        ],
        "producer_role": "strategy-runtime-requalification",
        "required_verifier": "qa-verifier-agent",
        "research_only": True,
        "paper_only": True,
        "candidate_creation_authority": False,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    core["strategy_config_digest"] = digest(core["strategy_config"])
    return {**core, "task_digest": digest(core)}


def _receipt(task, lease="qa-lease"):
    core = {
        "schema_version": "nexus.strategy-independent-qa-receipt.v1",
        "qa_lease_id": lease,
        "task_digest": task["task_digest"],
        "source_sha": task["source_sha"],
        "proposal_digest": task["proposal_digest"],
        "proposal_result_digest": task["proposal_result_digest"],
        "requalification_digest": task["requalification_digest"],
        "requalification_verification_digest": task["requalification_verification_digest"],
        "strategy_config_digest": task["strategy_config_digest"],
        "runtime_evidence": [
            {
                **row,
                "qualification_status": "paper_candidate",
                "deterministic_replay_verified": True,
            }
            for row in sorted(task["runtime_evidence"], key=lambda item: item["symbol"])
        ],
        "independent_qa_complete": True,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "qa_receipt_digest": digest(core)}


def _manager(status="DONE"):
    task = _handoff()
    row = {
        "id": task["id"],
        "status": status,
        "authority": 2,
        "qa_verifier_only": True,
        "qa_dispatch_enabled": True,
        "required_verifier": "qa-verifier-agent",
        "qa_handoff_task": task,
    }
    if status == "DONE":
        row.update(
            assigned_worker="qa-verifier-agent",
            verifier="qa-verifier-agent",
            lease_id="qa-lease",
            verification_evidence=_receipt(task),
        )
    return row


def test_done_independent_qa_qualifies_only_for_registry():
    result = evaluate_qualification(_manager())
    assert result["decision"] == "QUALIFIED_FOR_REGISTRY"
    assert result["qualified"] is True
    assert result["registry_admission_allowed"] is True
    assert len(result["runtime_evidence"]) == 2
    assert len(result["runtime_evidence_digest"]) == 64
    assert result["runtime_evidence_digest"] == digest(result["runtime_evidence"])
    assert result["registry_mutation_performed"] is False
    assert result["runtime_activation_authority"] is False
    assert result["paper_execution_authority"] is False
    assert result["live_trading_authority"] is False
    assert verify_qualification(result)["decision"] == "pass"


def test_tampered_or_self_approved_qa_never_qualifies():
    bad = _manager()
    bad["verification_evidence"]["runtime_evidence"][0]["pipeline_digest"] = "9" * 64
    with pytest.raises(StrategyQualificationError, match="exact accepted verifier receipt"):
        evaluate_qualification(bad)

    producer = _manager()
    producer["producer"] = "qa-verifier-agent"
    with pytest.raises(StrategyQualificationError, match="authority boundary"):
        evaluate_qualification(producer)


@pytest.mark.parametrize(
    ("status", "decision", "reason"),
    [
        ("VERIFYING", "WAITING_FOR_QA", "INDEPENDENT_QA_INCOMPLETE"),
        ("BLOCKED", "REJECTED", "INDEPENDENT_QA_BLOCKED"),
        ("QUARANTINED", "REJECTED", "INDEPENDENT_QA_QUARANTINED"),
    ],
)
def test_non_done_qa_cannot_enter_registry(status, decision, reason):
    result = evaluate_qualification(_manager(status))
    assert result["decision"] == decision
    assert result["qualified"] is False
    assert result["registry_admission_allowed"] is False
    assert result["reason_codes"] == [reason]
    assert result["qa_receipt_digest"] is None
    assert verify_qualification(result)["decision"] == "pass"


def test_qualification_is_deterministic_and_tamper_evident():
    first = evaluate_qualification(_manager())
    second = evaluate_qualification(deepcopy(_manager()))
    assert first == second
    tampered = deepcopy(first)
    tampered["runtime_activation_authority"] = True
    assert verify_qualification(tampered)["decision"] == "reject"

    evidence_tamper = deepcopy(first)
    evidence_tamper["runtime_evidence"][0]["pipeline_digest"] = "9" * 64
    assert verify_qualification(evidence_tamper)["decision"] == "reject"


def test_qualification_gate_import_is_control_plane_lightweight():
    import subprocess
    import sys

    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; "
                "sys.modules['pandas']=None; "
                "import nexus_strategy_qualification_gate as q; "
                "assert callable(q.verify_qualification); "
                "print('lightweight_qual42_import=PASS')"
            ),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "lightweight_qual42_import=PASS" in proc.stdout
