from __future__ import annotations

from copy import deepcopy

import pytest

import nexus_composite_runtime_qa_task_materializer as mat


def _task():
    return {
        "schema_version": "nexus.composite-runtime-qa-task.v1",
        "id": "COMPOSITE-QA-" + "a" * 64,
        "task_kind": "composite_runtime_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "required_verifier": "qa-verifier-agent",
        "producer_role": "physical-composite-val40-requalification",
        "source_sha": "b" * 40,
        "candidate_digest": "c" * 64,
        "requalification_digest": "a" * 64,
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "task_digest": "d" * 64,
    }


def _transport(task):
    return {
        "schema_version": "nexus.composite-runtime-qa-transport.v1",
        "producer_workflow_run_id": 101,
        "artifact_id": 202,
        "task_digest": task["task_digest"],
        "source_sha": task["source_sha"],
        "candidate_digest": task["candidate_digest"],
        "requalification_digest": task["requalification_digest"],
        "required_verifier": "qa-verifier-agent",
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
    }


def test_materializer_is_restart_safe_and_dispatch_disabled(monkeypatch):
    monkeypatch.setattr(mat, "validate_task", lambda value, source: dict(value))
    task = _task()
    definition = {"tasks": []}
    first = mat.materialize_composite_qa_task(definition, task, _transport(task))
    second = mat.materialize_composite_qa_task(first, task, _transport(task))
    assert first == second
    row = first["tasks"][0]
    assert row["id"] == task["id"]
    assert row["status"] == "BLOCKED"
    assert row["qa_verifier_only"] is True
    assert row["qa_dispatch_enabled"] is False
    assert row["required_verifier"] == "qa-verifier-agent"
    assert row["authority"] == 2
    assert row["paper_execution_authority"] if "paper_execution_authority" in row else False is False


def test_materializer_rejects_authority_widening(monkeypatch):
    monkeypatch.setattr(mat, "validate_task", lambda value, source: dict(value))
    task = _task()
    task["live_trading_authority"] = True
    with pytest.raises(mat.CompositeRuntimeQaTaskMaterializerError, match="authority boundary"):
        mat.materialize_composite_qa_task({"tasks": []}, task, _transport(task))


def test_materializer_rejects_definition_collision(monkeypatch):
    monkeypatch.setattr(mat, "validate_task", lambda value, source: dict(value))
    task = _task()
    first = mat.materialize_composite_qa_task({"tasks": []}, task, _transport(task))
    collision = deepcopy(first)
    collision["tasks"][0]["priority"] = 1
    with pytest.raises(mat.CompositeRuntimeQaTaskMaterializerError, match="collides"):
        mat.materialize_composite_qa_task(collision, task, _transport(task))
