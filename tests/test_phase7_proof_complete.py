from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_manager as am
import offline_agent_courier as courier
import phase7_e2e_proof
from phase5_state_store import SQLiteStateStore
from scripts import phase7_proof_complete as completion
from scripts import phase7_proof_prepare as prepare

SOURCE = "a" * 40
KEY = "phase7-completion-key-" + "x" * 40
WRONG_KEY = "phase7-wrong-key-" + "y" * 40


def _fake_e2e(source_sha: str) -> dict:
    core = {
        "schema_version": phase7_e2e_proof.SCHEMA,
        "source_sha": source_sha,
        "paper_only": True,
        "profitability_claim": False,
        "live_trading_authority": False,
        "strategy": {"qualification_status": "paper_candidate"},
        "risk": {"allowed": True},
        "paper": {"event_count": 1},
    }
    return {**core, "proof_digest": phase7_e2e_proof._digest(core)}


def _proof_executor(payload: dict, transport: str) -> dict:
    if transport == "windows":
        evidence = {
            "executor": "bounded-pytest",
            "workload_id": "P7-LAPTOP-CANONICAL",
            "purpose": "canonical-data-and-offline-backtest-proof",
            "suite": list(completion.EXPECTED_LAPTOP_SUITE),
            "offline_capable": True,
            "network_required": False,
            "transport": "windows",
            "tests": {"ok": True, "returncode": 0, "stdout": "21 passed", "stderr": ""},
            "failure_class": None,
        }
    else:
        evidence = {
            "executor": "phase7-proof-test",
            "workload_id": payload["task_id"],
            "transport": transport,
        }
    return {
        "schema_version": 2,
        "task_id": payload["task_id"],
        "lease_id": payload["lease_id"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
        "worker_id": payload["worker_id"],
        "transport": transport,
        "outcome": "success",
        "evidence": evidence,
    }


def _fake_verifier_run(cmd: list[str], timeout: int = 600) -> dict:
    assert cmd == ["python", "-m", "pytest", "-q", *completion.CLOUD_VERIFIER_SUITE]
    assert timeout == 900
    return {"ok": True, "returncode": 0, "stdout": "cloud verifier passed", "stderr": ""}


def _prepare_return(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    artifact = tmp_path / "artifact"
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setenv("NEXUS_PHASE7_TEST_VERIFIER", "1")
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(prepare.executor, "execute", _proof_executor)
    monkeypatch.setattr(prepare.phase7_e2e_proof, "build_proof", _fake_e2e)
    monkeypatch.setattr(prepare.phase7_e2e_proof, "validate_proof", lambda proof, expected_source_sha: None)
    prepare.prepare(SOURCE, artifact)

    dispatch = artifact / "courier" / "phase7-laptop-dispatch.json"
    returned = tmp_path / "phase7-laptop-result.json"
    assert dispatch.is_file()
    monkeypatch.setattr(courier.executor, "execute", _proof_executor)
    courier.execute_bundle(dispatch, returned)
    assert returned.is_file()
    return artifact, returned


def test_returned_laptop_result_reaches_verified_done_and_100_percent(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    monkeypatch.setattr(completion.executor, "run", _fake_verifier_run)
    before = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    assert before["manager_summary"]["verified_progress_percent"] == 75.0
    assert before["courier"]["status"] == "EXPORTED"
    assert before["zero_idle_evidence"]["rule"] == "dispatch_independent_ready_work_while_other_resource_waits"

    completed = completion.complete(artifact, returned)
    assert completed["hardware_proof_complete"] is True
    assert completed["core_cloud_chain_complete"] is True
    assert completed["courier"]["status"] == "EXECUTED_AND_VERIFIED"
    assert completed["manager_summary"]["verified_progress_percent"] == 100.0
    assert completed["manager_summary"]["counts"] == {"DONE": 4}
    assert completed["state_generation"] > before["state_generation"]
    assert completed["state_sha256"] != before["state_sha256"]

    runtime = json.loads((artifact / "agent-manager-runtime.json").read_text(encoding="utf-8"))
    laptop = am.task_index(runtime)[completion.TASK_ID]
    assert laptop["status"] == "DONE"
    assert laptop["producer"] == completion.EXPECTED_PRODUCER
    assert laptop["verifier"] == completion.EXPECTED_VERIFIER
    assert laptop["verification_evidence"]["schema_version"] == completion.VERIFY_SCHEMA
    assert laptop["verification_evidence"]["accepted"] is True
    assert laptop["verification_evidence"]["producer_trust_domain"] == "windows-local"
    assert laptop["verification_evidence"]["verifier_trust_domain"] == "github-cloud-verifier"
    assert laptop["verification_evidence"]["verifier_tests"]["ok"] is True

    roles = [
        row["role"] for row in completed["resource_ledger"]
        if row.get("task_id") == completion.TASK_ID
    ]
    assert roles == ["producer", "producer_result", "verifier"]
    assert completed["resource_ledger"][-2]["resource"] == "windows-local"
    assert completed["resource_ledger"][-1]["resource"] == "github-cloud-verifier"

    current = SQLiteStateStore(artifact / "phase7-supervisor-state.sqlite3").load_current(prepare.MISSION_ID)
    assert current is not None
    assert current.generation == completed["state_generation"]
    assert current.payload_sha256 == completed["state_sha256"]
    assert am.task_index(current.payload)[completion.TASK_ID]["status"] == "DONE"


def test_completion_replay_is_rejected_after_verified_done(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    monkeypatch.setattr(completion.executor, "run", _fake_verifier_run)
    completion.complete(artifact, returned)
    with pytest.raises(completion.Phase7CompletionError, match="already completed"):
        completion.complete(artifact, returned)


def test_wrong_courier_key_rejects_return_without_advancing_durable_state(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    monkeypatch.setattr(completion.executor, "run", _fake_verifier_run)
    before = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    monkeypatch.setenv(courier.KEY_ENV, WRONG_KEY)

    with pytest.raises(ValueError, match="signature mismatch"):
        completion.complete(artifact, returned)

    after = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    assert after == before
    current = SQLiteStateStore(artifact / "phase7-supervisor-state.sqlite3").load_current(prepare.MISSION_ID)
    assert current is not None
    assert current.generation == before["state_generation"]
    assert current.payload_sha256 == before["state_sha256"]


def test_completion_requires_independent_github_cloud_environment(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    monkeypatch.delenv("NEXUS_PHASE7_TEST_VERIFIER", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(completion.Phase7CompletionError, match="must run on GitHub Actions"):
        completion.complete(artifact, returned)


def test_failed_cloud_verifier_does_not_commit_completion(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    before = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        completion.executor,
        "run",
        lambda *_args, **_kwargs: {"ok": False, "returncode": 1, "stdout": "", "stderr": "failed"},
    )
    with pytest.raises(completion.Phase7CompletionError, match="cloud verifier"):
        completion.complete(artifact, returned)
    after = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    assert after == before
    current = SQLiteStateStore(artifact / "phase7-supervisor-state.sqlite3").load_current(prepare.MISSION_ID)
    assert current is not None
    assert current.generation == before["state_generation"]
