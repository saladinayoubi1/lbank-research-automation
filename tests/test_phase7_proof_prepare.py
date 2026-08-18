from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import agent_manager as am
import phase7_e2e_proof
from scripts import phase7_proof_prepare as runner


SOURCE = "a" * 40
KEY = "phase7-proof-test-key-" + "x" * 40


def _fake_executor(payload: dict, transport: str) -> dict:
    return {
        "schema_version": 2,
        "task_id": payload["task_id"],
        "lease_id": payload["lease_id"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
        "worker_id": payload["worker_id"],
        "transport": transport,
        "outcome": "success",
        "evidence": {
            "executor": "phase7-proof-test",
            "workload_id": payload["task_id"],
            "worker_id": payload["worker_id"],
        },
    }


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


def test_phase7_mission_routes_real_producers_to_intended_resources():
    cfg = runner.load_runtime_template()
    summary = am.cycle(cfg)
    tasks = am.task_index(cfg)

    assert tasks["P7-LAPTOP-CANONICAL"]["status"] == "LEASED"
    assert tasks["P7-LAPTOP-CANONICAL"]["assigned_worker"] == "windows-runner"
    assert tasks["P7-CLOUD-VERIFY"]["status"] == "LEASED"
    assert tasks["P7-CLOUD-VERIFY"]["assigned_worker"] == "cloud-worker"
    assert tasks["P7-RESEARCH-STRATEGY"]["status"] == "PENDING"
    assert tasks["P7-PAPER-PERFORMANCE"]["status"] == "PENDING"
    assert summary["owner_required"] == []


def test_prepare_with_courier_key_completes_cloud_chain_and_records_zero_idle(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("NEXUS_OFFLINE_COURIER_KEY", KEY)
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(runner.executor, "execute", _fake_executor)
    monkeypatch.setattr(runner.phase7_e2e_proof, "build_proof", _fake_e2e)
    monkeypatch.setattr(runner.phase7_e2e_proof, "validate_proof", lambda proof, expected_source_sha: None)

    result = runner.prepare(SOURCE, tmp_path)
    runtime = json.loads((tmp_path / "agent-manager-runtime.json").read_text(encoding="utf-8"))
    tasks = am.task_index(runtime)

    assert result["core_cloud_chain_complete"] is True
    assert result["hardware_proof_complete"] is False
    assert result["courier"]["status"] == "EXPORTED"
    assert result["courier"]["resource"] == "windows-local"
    assert result["deepseek"]["status"] == "UNAVAILABLE"
    assert tasks["P7-LAPTOP-CANONICAL"]["external_wait_state"] == am.WAITING_EXTERNAL
    assert tasks["P7-RESEARCH-STRATEGY"]["zero_idle_evidence"]["rule"] == "dispatch_independent_ready_work_while_other_resource_waits"
    overlap = tasks["P7-RESEARCH-STRATEGY"]["zero_idle_evidence"]["overlapped_external_waits"]
    assert [row["task_id"] for row in overlap] == ["P7-LAPTOP-CANONICAL"]

    by_task = {}
    for row in result["resource_ledger"]:
        by_task.setdefault(row["task_id"], []).append(row)
    for task_id in ("P7-CLOUD-VERIFY", "P7-RESEARCH-STRATEGY", "P7-PAPER-PERFORMANCE"):
        assert {row["role"] for row in by_task[task_id]} == {"producer", "verifier"}
        producer = next(row for row in by_task[task_id] if row["role"] == "producer")
        verifier = next(row for row in by_task[task_id] if row["role"] == "verifier")
        assert producer["worker_id"] != verifier["worker_id"]
        assert producer["lease_id"] != verifier["lease_id"]
        assert producer["dispatch_id"] != verifier["dispatch_id"]


def test_prepare_without_courier_key_never_fabricates_hardware_dispatch(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("NEXUS_OFFLINE_COURIER_KEY", raising=False)
    monkeypatch.setattr(runner.executor, "execute", _fake_executor)
    monkeypatch.setattr(runner.phase7_e2e_proof, "build_proof", _fake_e2e)
    monkeypatch.setattr(runner.phase7_e2e_proof, "validate_proof", lambda proof, expected_source_sha: None)

    result = runner.prepare(SOURCE, tmp_path)
    runtime = json.loads((tmp_path / "agent-manager-runtime.json").read_text(encoding="utf-8"))
    laptop = am.task_index(runtime)["P7-LAPTOP-CANONICAL"]

    assert result["courier"]["status"] == "KEY_UNAVAILABLE"
    assert result["hardware_proof_complete"] is False
    assert "payload_sha256" not in result["courier"]
    assert laptop.get("dispatch_mode") is None
    assert laptop.get("offline_dispatch_digest") is None
    assert not (tmp_path / "courier" / "phase7-laptop-dispatch.json").exists()


def test_deepseek_is_never_reported_executed_without_real_call(monkeypatch):
    monkeypatch.setenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "present-but-not-used-by-this-proof")
    status = runner._deepseek_status()
    assert status["status"] == "NOT_SELECTED"
    assert status["status"] != "EXECUTED"
