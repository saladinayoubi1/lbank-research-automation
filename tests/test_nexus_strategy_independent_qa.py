from __future__ import annotations

from copy import deepcopy
import hashlib
import json

import pytest

from nexus_strategy_independent_qa import (
    StrategyIndependentQaError,
    run_independent_qa,
    verify_receipt,
)


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


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
    core["strategy_config_digest"] = _digest(core["strategy_config"])
    return {**core, "task_digest": _digest(core)}


def _evaluator(task):
    expected = {row["symbol"]: row for row in task["runtime_evidence"]}

    def evaluator(proposal, symbol, source_sha, now_ms, state_root):
        row = expected[symbol]
        assert proposal["strategy_config"] == task["strategy_config"]
        assert source_sha == task["source_sha"]
        assert now_ms == row["last_open_time_ms"] + 14_400_000
        return {
            "symbol": symbol,
            "family": task["family"],
            "timeframe": task["timeframe"],
            "variant_id": task["variant_id"],
            "runtime_dataset_binding_sha256": row["dataset_binding_sha256"],
            "runtime_last_open_time_ms": row["last_open_time_ms"],
            "qualification_status": "paper_candidate",
            "pipeline_digest": row["pipeline_digest"],
            "qualification_digest": row["qualification_digest"],
            "kill_reasons": [],
            "deterministic_replay_verified": True,
            "data_origin": "canonical_public_bybit_runtime",
            "closed_candle_finality_verified": True,
            "paper_only": True,
            "live_trading_authority": False,
            "paper_execution_started": False,
            "automatic_strategy_promotion": False,
            "deterministic_risk_final_authority": True,
        }

    return evaluator


def test_exact_config_and_dataset_window_replay_produces_bound_receipt(tmp_path):
    task = _task()
    receipt = run_independent_qa(
        task,
        lease_id="qa-lease",
        execution_source_sha=task["source_sha"],
        state_root=tmp_path,
        evaluator=_evaluator(task),
    )
    assert receipt["independent_qa_complete"] is True
    assert receipt["qualification_authority"] is False
    assert receipt["paper_execution_authority"] is False
    assert receipt["live_trading_authority"] is False
    assert verify_receipt(
        receipt, task, lease_id="qa-lease", execution_source_sha=task["source_sha"]
    )


def test_replay_binding_mismatch_fails_closed(tmp_path):
    task = _task()

    def bad(proposal, symbol, source_sha, now_ms, state_root):
        row = _evaluator(task)(proposal, symbol, source_sha, now_ms, state_root)
        row["runtime_dataset_binding_sha256"] = "9" * 64
        return row

    with pytest.raises(StrategyIndependentQaError, match="replay mismatch"):
        run_independent_qa(
            task,
            lease_id="qa-lease",
            execution_source_sha=task["source_sha"],
            state_root=tmp_path,
            evaluator=bad,
        )


def test_wrong_source_or_tampered_config_cannot_replay(tmp_path):
    task = _task()
    with pytest.raises(StrategyIndependentQaError, match="authority or identity"):
        run_independent_qa(
            task,
            lease_id="qa-lease",
            execution_source_sha="0" * 40,
            state_root=tmp_path,
            evaluator=_evaluator(task),
        )

    tampered = deepcopy(task)
    tampered["strategy_config"]["lookback"] = 99
    with pytest.raises(StrategyIndependentQaError, match="authority or identity"):
        run_independent_qa(
            tampered,
            lease_id="qa-lease",
            execution_source_sha=task["source_sha"],
            state_root=tmp_path,
            evaluator=_evaluator(task),
        )


def test_receipt_tamper_is_rejected(tmp_path):
    task = _task()
    receipt = run_independent_qa(
        task,
        lease_id="qa-lease",
        execution_source_sha=task["source_sha"],
        state_root=tmp_path,
        evaluator=_evaluator(task),
    )
    tampered = deepcopy(receipt)
    tampered["runtime_evidence"][0]["pipeline_digest"] = "8" * 64
    assert not verify_receipt(
        tampered, task, lease_id="qa-lease", execution_source_sha=task["source_sha"]
    )


def test_receipt_with_extra_field_is_rejected_even_if_redigested(tmp_path):
    task = _task()
    receipt = run_independent_qa(
        task,
        lease_id="qa-lease",
        execution_source_sha=task["source_sha"],
        state_root=tmp_path,
        evaluator=_evaluator(task),
    )
    tampered = deepcopy(receipt)
    tampered["unexpected"] = "field"
    core = dict(tampered)
    core.pop("qa_receipt_digest")
    tampered["qa_receipt_digest"] = _digest(core)
    assert not verify_receipt(
        tampered, task, lease_id="qa-lease", execution_source_sha=task["source_sha"]
    )
