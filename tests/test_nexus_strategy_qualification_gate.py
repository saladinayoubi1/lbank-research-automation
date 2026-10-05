from __future__ import annotations

from copy import deepcopy

import pytest

from nexus_strategy_independent_qa import digest
from nexus_strategy_qualification_gate import (
    StrategyQualificationError,
    qualify_for_registry,
    verify_qualification,
)
from strategy_registry import (
    StrategyRegistryError,
    validate_approved_strategy_record,
)


def _task():
    core = {
        "schema_version": "nexus.strategy-review-qa-task.v1",
        "id": "STRATEGY-QA-" + "a" * 64,
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
        "strategy_config": {"lookback": 16, "entry_threshold": 0.0015},
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


def _receipt(task, lease_id="qa-lease"):
    runtime = [
        {
            **row,
            "qualification_status": "paper_candidate",
            "deterministic_replay_verified": True,
        }
        for row in sorted(task["runtime_evidence"], key=lambda item: item["symbol"])
    ]
    core = {
        "schema_version": "nexus.strategy-independent-qa-receipt.v1",
        "qa_lease_id": lease_id,
        "task_digest": task["task_digest"],
        "source_sha": task["source_sha"],
        "proposal_digest": task["proposal_digest"],
        "proposal_result_digest": task["proposal_result_digest"],
        "requalification_digest": task["requalification_digest"],
        "requalification_verification_digest": task["requalification_verification_digest"],
        "strategy_config_digest": task["strategy_config_digest"],
        "runtime_evidence": runtime,
        "independent_qa_complete": True,
        "qualification_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }
    return {**core, "qa_receipt_digest": digest(core)}


def test_valid_independent_qa_qualifies_only_for_registry():
    task = _task()
    receipt = _receipt(task)

    result = qualify_for_registry(task, receipt, expected_qa_lease_id="qa-lease")

    assert result["qualified"] is True
    assert result["registry_admission_allowed"] is True
    assert result["demo_matrix_membership"] is False
    assert result["paper_execution_authority"] is False
    assert result["automatic_demo_admission"] is False
    assert result["live_trading_authority"] is False
    assert result["reason_codes"] == [
        "INDEPENDENT_QA_VERIFIED",
        "EXACT_SOURCE_CONFIG_DATASET_BOUND",
    ]

    record = validate_approved_strategy_record(result["approved_strategy_record"])
    assert record["proposal_digest"] == task["proposal_digest"]
    assert record["qa_task_digest"] == task["task_digest"]
    assert record["qa_receipt_digest"] == receipt["qa_receipt_digest"]
    assert record["qualification_digest"] == result["qualification_digest"]
    assert record["config"] == task["strategy_config"]
    assert record["demo_matrix_membership"] is False
    assert record["registry_mutation_authority"] is False
    assert record["paper_execution_authority"] is False
    assert record["live_trading_authority"] is False


def test_tampered_or_wrong_lease_qa_receipt_is_rejected_without_registry_record():
    task = _task()
    receipt = _receipt(task)

    tampered = deepcopy(receipt)
    tampered["runtime_evidence"][0]["pipeline_digest"] = "9" * 64
    rejected = qualify_for_registry(task, tampered, expected_qa_lease_id="qa-lease")
    assert rejected["qualified"] is False
    assert rejected["registry_admission_allowed"] is False
    assert rejected["approved_strategy_record"] is None
    assert rejected["reason_codes"] == ["INDEPENDENT_QA_RECEIPT_REJECTED"]

    wrong_lease = qualify_for_registry(task, receipt, expected_qa_lease_id="other-lease")
    assert wrong_lease["qualified"] is False
    assert wrong_lease["approved_strategy_record"] is None


def test_invalid_qa_task_cannot_reach_qualification():
    task = _task()
    receipt = _receipt(task)
    task["strategy_config"]["lookback"] = 99

    with pytest.raises(StrategyQualificationError, match="invalid QA-41 task"):
        qualify_for_registry(task, receipt, expected_qa_lease_id="qa-lease")


def test_qualification_and_approved_record_tamper_fail_closed():
    task = _task()
    receipt = _receipt(task)
    result = qualify_for_registry(task, receipt, expected_qa_lease_id="qa-lease")
    assert verify_qualification(
        result, task, receipt, expected_qa_lease_id="qa-lease"
    )["decision"] == "pass"

    tampered_qualification = deepcopy(result)
    tampered_qualification["registry_admission_allowed"] = False
    assert verify_qualification(
        tampered_qualification, task, receipt, expected_qa_lease_id="qa-lease"
    )["decision"] == "reject"

    tampered_record = deepcopy(result["approved_strategy_record"])
    tampered_record["demo_matrix_membership"] = True
    with pytest.raises(StrategyRegistryError):
        validate_approved_strategy_record(tampered_record)


def test_qualification_is_deterministic_for_identical_inputs():
    task = _task()
    receipt = _receipt(task)

    first = qualify_for_registry(task, receipt, expected_qa_lease_id="qa-lease")
    second = qualify_for_registry(
        deepcopy(task), deepcopy(receipt), expected_qa_lease_id="qa-lease"
    )

    assert first == second
    assert first["qualification_digest"] == second["qualification_digest"]
    assert (
        first["approved_strategy_record"]["record_digest"]
        == second["approved_strategy_record"]["record_digest"]
    )
