from __future__ import annotations

import io
import json
import zipfile

import pytest

import nexus_composite_runtime_qa_transport as tr


SOURCE = "b" * 40
CURRENT = "c" * 40


def _artifact_blob(producer=None, verification=None):
    producer = producer or {
        "decision": "QUALIFIED_FOR_REVIEW",
        "qualified_for_review": True,
        "requalification_source_sha": SOURCE,
        "candidate_digest": "d" * 64,
        "requalification_digest": "e" * 64,
    }
    verification = verification or {"decision": "pass", "verification_digest": "f" * 64}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("runtime-requalification.json", json.dumps(producer))
        zf.writestr("verification.json", json.dumps(verification))
    return buf.getvalue()


def _task():
    return {
        "schema_version": "nexus.composite-runtime-qa-task.v1",
        "id": "COMPOSITE-QA-" + "e" * 64,
        "task_kind": "composite_runtime_independent_qa",
        "system_map_node": "QA-41",
        "status": "READY_FOR_QA_DISPATCH",
        "required_verifier": "qa-verifier-agent",
        "producer_role": "physical-composite-val40-requalification",
        "producer_workflow_run_id": 101,
        "source_sha": SOURCE,
        "candidate_digest": "d" * 64,
        "requalification_digest": "e" * 64,
        "requalification_verification_digest": "f" * 64,
        "evaluations_digest": "1" * 64,
        "runtime_as_of_ms": 1_800_000_000_000,
        "producer": {},
        "producer_verification": {},
        "research_only": True,
        "paper_only": True,
        "qualification_authority": False,
        "registry_mutation_authority": False,
        "runtime_activation_authority": False,
        "promotion_authority": False,
        "paper_execution_authority": False,
        "automatic_strategy_promotion": False,
        "live_trading_authority": False,
        "task_digest": "2" * 64,
    }


def test_parse_artifact_requires_exact_verification():
    producer = {
        "decision": "QUALIFIED_FOR_REVIEW",
        "qualified_for_review": True,
        "requalification_source_sha": SOURCE,
    }
    proof = {"decision": "pass", "verification_digest": "a" * 64}
    parsed, verification = tr.parse_artifact(
        _artifact_blob(producer, proof),
        verifier=lambda value: dict(proof),
    )
    assert parsed == producer
    assert verification == proof

    with pytest.raises(tr.CompositeRuntimeQaTransportError, match="verification rejected"):
        tr.parse_artifact(
            _artifact_blob(producer, proof),
            verifier=lambda value: {"decision": "reject"},
        )


def test_latest_verified_task_accepts_only_trusted_main_ancestor(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    proof = {"decision": "pass", "verification_digest": "f" * 64}

    def api(method, url, payload):
        if "/actions/workflows/" in url:
            return {
                "workflow_runs": [{
                    "id": 101,
                    "conclusion": "success",
                    "head_branch": "main",
                    "event": "workflow_dispatch",
                    "head_sha": SOURCE,
                }]
            }
        if "/actions/runs/101/artifacts" in url:
            return {
                "artifacts": [{
                    "id": 202,
                    "name": "nexus-composite-runtime-requalification-101",
                    "expired": False,
                    "size_in_bytes": 1000,
                }]
            }
        if "/compare/" in url:
            return {
                "status": "ahead",
                "ahead_by": 2,
                "behind_by": 0,
                "merge_base_commit": {"sha": SOURCE},
            }
        raise AssertionError(url)

    task = _task()
    result = tr.latest_verified_task(
        current_sha=CURRENT,
        api=api,
        downloader=lambda artifact_id: _artifact_blob(verification=proof),
        verifier=lambda value: dict(proof),
        builder=lambda producer, verification, producer_workflow_run_id: dict(task),
        validator=lambda value, source: dict(value),
    )
    assert result is not None
    qa_task, transport = result
    assert qa_task == task
    assert transport["producer_workflow_run_id"] == 101
    assert transport["artifact_id"] == 202
    assert transport["task_digest"] == task["task_digest"]
    assert transport["paper_execution_authority"] is False
    assert transport["live_trading_authority"] is False


def test_latest_verified_task_rejects_diverged_source(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "saladinayoubi1/lbank-research-automation")
    proof = {"decision": "pass", "verification_digest": "f" * 64}

    def api(method, url, payload):
        if "/actions/workflows/" in url:
            return {"workflow_runs": [{
                "id": 101, "conclusion": "success", "head_branch": "main",
                "event": "workflow_dispatch", "head_sha": SOURCE,
            }]}
        if "/actions/runs/101/artifacts" in url:
            return {"artifacts": [{
                "id": 202,
                "name": "nexus-composite-runtime-requalification-101",
                "expired": False,
                "size_in_bytes": 1000,
            }]}
        if "/compare/" in url:
            return {
                "status": "diverged",
                "ahead_by": 1,
                "behind_by": 1,
                "merge_base_commit": {"sha": "0" * 40},
            }
        raise AssertionError(url)

    with pytest.raises(tr.CompositeRuntimeQaTransportError, match="not trusted main ancestry"):
        tr.latest_verified_task(
            current_sha=CURRENT,
            api=api,
            downloader=lambda artifact_id: _artifact_blob(verification=proof),
            verifier=lambda value: dict(proof),
            builder=lambda producer, verification, producer_workflow_run_id: _task(),
            validator=lambda value, source: dict(value),
        )


def test_store_is_idempotent_and_collision_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "validate_task", lambda value, source: dict(value))
    task = _task()
    transport = {
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
    first = tr.store_verified_task(tmp_path, task, transport)
    second = tr.store_verified_task(tmp_path, task, transport)
    assert first == second
    tampered = dict(transport)
    tampered["artifact_id"] = 999
    with pytest.raises(tr.CompositeRuntimeQaTransportError, match="collision"):
        tr.store_verified_task(tmp_path, task, tampered)
