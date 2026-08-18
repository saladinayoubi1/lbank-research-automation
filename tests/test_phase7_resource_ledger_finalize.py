from __future__ import annotations

import json
from pathlib import Path

import agent_manager as am
import offline_agent_courier as courier
import phase7_e2e_proof
from scripts import phase7_proof_complete as secure_completion
from scripts import phase7_proof_prepare as prepare
from scripts import phase7_resource_ledger_finalize as finalizer

SOURCE = "a" * 40
KEY = "phase7-ledger-finalize-key-" + "x" * 40


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


def _executor(payload: dict, transport: str) -> dict:
    if transport == "windows":
        evidence = {
            "executor": "bounded-pytest",
            "workload_id": "P7-LAPTOP-CANONICAL",
            "purpose": "canonical-data-and-offline-backtest-proof",
            "suite": list(secure_completion.EXPECTED_LAPTOP_SUITE),
            "offline_capable": True,
            "network_required": False,
            "transport": "windows",
            "tests": {"ok": True, "returncode": 0, "stdout": "offline passed", "stderr": ""},
            "failure_class": None,
        }
    else:
        evidence = {
            "executor": "phase7-ledger-test",
            "workload_id": payload["task_id"],
            "worker_id": payload["worker_id"],
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


def _verifier_run(cmd: list[str], timeout: int = 600) -> dict:
    assert cmd == ["python", "-m", "pytest", "-q", *secure_completion.CLOUD_VERIFIER_SUITE]
    assert timeout == 900
    return {"ok": True, "returncode": 0, "stdout": "cloud verifier passed", "stderr": ""}


def _prepare_return(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    artifact = tmp_path / "artifact"
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setenv("NEXUS_PHASE7_TEST_VERIFIER", "1")
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(prepare.executor, "execute", _executor)
    monkeypatch.setattr(prepare.phase7_e2e_proof, "build_proof", _fake_e2e)
    prepare.prepare(SOURCE, artifact)

    dispatch = artifact / "courier" / "phase7-laptop-dispatch.json"
    returned = tmp_path / "phase7-laptop-result.json"
    monkeypatch.setattr(courier.executor, "execute", _executor)
    courier.execute_bundle(dispatch, returned)
    monkeypatch.setattr(secure_completion.executor, "run", _verifier_run)
    return artifact, returned


def _assert_normalized_row(row: dict) -> None:
    assert row["classification"] in {"EXECUTED", "UNAVAILABLE"}
    assert row["resource_class"] in prepare.RESOURCE_CLASSES
    assert row["task_id"]
    assert row["worker_id"]
    assert isinstance(row["routing"], dict)
    assert isinstance(row["routing"]["rejected_alternatives"], list)
    assert row["lease_fencing"]["lease_id"]
    assert row["lease_fencing"]["dispatch_id"]
    assert len(row["lease_fencing"]["fencing_identity_sha256"]) == 64
    assert set(row["timestamps"]) == {"leased_at", "dispatch_at", "heartbeat_at", "result_at"}
    assert set(row["result"]) == {"outcome", "evidence_sha256", "failure_class"}
    assert set(row["verifier"]) == {"worker_id", "result"}
    assert set(row["retry_failure"]) == {"transient_retries", "observed_failure_rate"}
    assert set(row["budget_cost"]) == {"routing_cost_units", "provider_cost_usd"}


def test_finalizer_replaces_waiting_laptop_with_executed_and_verified_rows(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    before = json.loads((artifact / "phase7-proof-mission-run.json").read_text(encoding="utf-8"))
    assert before["resource_classification"]["Laptop"]["classification"] == "UNAVAILABLE"
    assert before["resource_classification"]["Internal Agent"]["classification"] == "EXECUTED"
    assert before["resource_classification"]["Cloud/GitHub worker"]["classification"] == "EXECUTED"
    assert before["resource_classification"]["DeepSeek/AI provider"]["classification"] == "UNAVAILABLE"

    completed = finalizer.finalize(artifact, returned)

    assert completed["hardware_proof_complete"] is True
    assert completed["manager_summary"]["verified_progress_percent"] == 100.0
    classes = completed["resource_classification"]
    assert classes["Laptop"]["classification"] == "EXECUTED"
    assert classes["Internal Agent"]["classification"] == "EXECUTED"
    assert classes["Cloud/GitHub worker"]["classification"] == "EXECUTED"
    assert classes["DeepSeek/AI provider"]["classification"] == "UNAVAILABLE"

    laptop_rows = [row for row in completed["resource_ledger"] if row.get("task_id") == finalizer.TASK_ID]
    assert {(row["role"], row["worker_id"]) for row in laptop_rows} == {
        ("producer", finalizer.EXPECTED_PRODUCER),
        ("verifier", finalizer.EXPECTED_VERIFIER),
    }
    assert all(row["classification"] == "EXECUTED" for row in laptop_rows)
    assert not any(row.get("role") == "producer_result" for row in laptop_rows)
    producer = next(row for row in laptop_rows if row["role"] == "producer")
    verifier = next(row for row in laptop_rows if row["role"] == "verifier")
    assert producer["resource_class"] == "Laptop"
    assert producer["result"]["outcome"] == "success"
    assert producer["verifier"] == {"worker_id": finalizer.EXPECTED_VERIFIER, "result": "success"}
    assert producer["result_bundle_sha256"] == completed["courier"]["result_bundle_sha256"]
    assert verifier["resource_class"] == "Cloud/GitHub worker"
    assert verifier["result"]["outcome"] == "success"
    assert verifier["routing"]["selected_worker"] == finalizer.EXPECTED_VERIFIER
    for row in completed["resource_ledger"]:
        _assert_normalized_row(row)

    runtime = json.loads((artifact / "agent-manager-runtime.json").read_text(encoding="utf-8"))
    assert am.task_index(runtime)[finalizer.TASK_ID]["status"] == "DONE"


def test_finalizer_is_idempotent_after_normalization(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    first = finalizer.finalize(artifact, returned)
    second = finalizer.finalize(artifact, returned)
    assert second == first
    assert second["resource_classification"]["Laptop"]["classification"] == "EXECUTED"


def test_finalizer_recovers_if_secure_completion_finished_before_ledger_normalization(monkeypatch, tmp_path: Path):
    artifact, returned = _prepare_return(monkeypatch, tmp_path)
    run_path = artifact / "phase7-proof-mission-run.json"
    prepared = json.loads(run_path.read_text(encoding="utf-8"))
    secure_completion._write_json(artifact / "phase7-proof-prepared-run.json", prepared)
    raw_completed = secure_completion.complete(artifact, returned)
    assert raw_completed["hardware_proof_complete"] is True
    assert any(row.get("role") == "producer_result" for row in raw_completed["resource_ledger"])

    normalized = finalizer.finalize(artifact, returned)
    assert normalized["resource_classification"]["Laptop"]["classification"] == "EXECUTED"
    assert not any(
        row.get("task_id") == finalizer.TASK_ID and row.get("role") == "producer_result"
        for row in normalized["resource_ledger"]
    )
