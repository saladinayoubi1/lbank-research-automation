from __future__ import annotations

from copy import deepcopy

import pytest

from nexus_strategy_qa_task_materializer import (
    StrategyQaTaskMaterializerError,
    materialize_qa_tasks,
)
from nexus_strategy_review_qa_handoff import verify_handoff


def _handoff():
    task_core = {
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
        "strategy_config": {"lookback": 16},
        "strategy_config_digest": "",
        "runtime_evidence": [{"symbol": "BTCUSDT", "dataset_binding_sha256": "f"*64, "pipeline_digest": "1"*64, "qualification_digest": "2"*64}],
        "producer_role": "strategy-runtime-requalification",
        "required_verifier": "qa-verifier-agent",
        "research_only": True, "paper_only": True,
        "candidate_creation_authority": False, "qualification_authority": False,
        "promotion_authority": False, "paper_execution_authority": False,
        "automatic_strategy_promotion": False, "live_trading_authority": False,
    }
    import hashlib, json
    digest=lambda v: hashlib.sha256(json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    task_core["strategy_config_digest"]=digest(task_core["strategy_config"])
    task={**task_core,"task_digest":digest(task_core)}
    core={
        "schema_version":"nexus.strategy-review-qa-handoff.v1","source_sha":"b"*40,
        "requalification_digest":"d"*64,"requalification_verification_digest":"e"*64,
        "status":"READY_FOR_QA","task_count":1,"tasks":[task],
        "required_verifier":"qa-verifier-agent","research_only":True,"paper_only":True,
        "candidate_creation_authority":False,"qualification_authority":False,
        "promotion_authority":False,"paper_execution_authority":False,
        "automatic_strategy_promotion":False,"live_trading_authority":False,
    }
    return {**core,"handoff_digest":digest(core)}


def _definition():
    return {"schema_version": 1, "phase": 4, "policy": {}, "workers": [], "tasks": []}


def test_materializer_is_restart_safe_and_verifier_only():
    handoff=_handoff()
    proof=verify_handoff(handoff)
    assert proof["decision"]=="pass"
    first=materialize_qa_tasks(_definition(),handoff,proof)
    second=materialize_qa_tasks(first,handoff,proof)
    assert first==second
    task=first["tasks"][0]
    assert task["id"]=="STRATEGY-QA-"+"a"*64
    assert task["qa_verifier_only"] is True
    assert task["qa_dispatch_enabled"] is False
    assert task["status"] == "BLOCKED"
    assert task["required_verifier"]=="qa-verifier-agent"
    assert task["required_resources"]==["github-cloud"]
    assert task["authority"]==2
    assert task["qa_handoff_task"]["paper_execution_authority"] is False
    assert task["qa_handoff_task"]["live_trading_authority"] is False


def test_materializer_rejects_stale_or_tampered_handoff():
    handoff=_handoff()
    proof=verify_handoff(handoff)
    tampered=deepcopy(handoff)
    tampered["tasks"][0]["strategy_config"]["lookback"]=99
    with pytest.raises(StrategyQaTaskMaterializerError, match="verification"):
        materialize_qa_tasks(_definition(),tampered,proof)


def test_materializer_rejects_definition_collision():
    handoff=_handoff()
    proof=verify_handoff(handoff)
    definition=_definition()
    definition["tasks"]=[{"id":"STRATEGY-QA-"+"a"*64,"status":"DONE"}]
    with pytest.raises(StrategyQaTaskMaterializerError, match="collides"):
        materialize_qa_tasks(definition,handoff,proof)
