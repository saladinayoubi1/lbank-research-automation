from __future__ import annotations

import json
from pathlib import Path

import agent_manager as am
import phase7_e2e_proof
from scripts import phase7_proof_prepare as runner


SOURCE = "a" * 40
KEY = "phase7-proof-test-key-" + "x" * 40


def _fake_executor(payload: dict, transport: str) -> dict:
    evidence = {
        "executor": "phase7-proof-test",
        "workload_id": payload["task_id"],
        "worker_id": payload["worker_id"],
    }
    if transport == "deepseek":
        evidence.update({"provider": "deepseek", "model": "deepseek-test", "cost_usd": 0.001})
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


def _assert_ledger_contract(row: dict) -> None:
    assert row["classification"] in {"EXECUTED", "UNAVAILABLE"}
    assert row["resource_class"] in runner.RESOURCE_CLASSES
    assert row["task_id"]
    assert row["worker_id"]
    assert isinstance(row["routing"], dict)
    assert "selected_worker" in row["routing"]
    assert "rejected_alternatives" in row["routing"]
    assert isinstance(row["routing"]["rejected_alternatives"], list)
    assert row["lease_fencing"]["attempt"] >= 1
    assert row["lease_fencing"]["lease_id"]
    assert row["lease_fencing"]["dispatch_id"]
    assert len(row["lease_fencing"]["fencing_identity_sha256"]) == 64
    assert set(row["timestamps"]) == {"leased_at", "dispatch_at", "heartbeat_at", "result_at"}
    assert set(row["result"]) == {"outcome", "evidence_sha256", "failure_class"}
    assert set(row["verifier"]) == {"worker_id", "result"}
    assert set(row["retry_failure"]) == {"transient_retries", "observed_failure_rate"}
    assert set(row["budget_cost"]) == {"routing_cost_units", "provider_cost_usd"}


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


def test_prepare_with_courier_key_completes_cloud_chain_and_records_acceptance_ledger(monkeypatch, tmp_path: Path):
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
    assert result["deepseek"]["status"] == "UNAVAILABLE"
    assert result["deepseek"]["reason"] == "missing_provider_configuration"
    assert tasks["P7-LAPTOP-CANONICAL"]["external_wait_state"] == am.WAITING_EXTERNAL
    assert tasks["P7-RESEARCH-STRATEGY"]["zero_idle_evidence"]["rule"] == "dispatch_independent_ready_work_while_other_resource_waits"
    overlap = tasks["P7-RESEARCH-STRATEGY"]["zero_idle_evidence"]["overlapped_external_waits"]
    assert [row["task_id"] for row in overlap] == ["P7-LAPTOP-CANONICAL"]

    for row in result["resource_ledger"]:
        _assert_ledger_contract(row)

    laptop = next(row for row in result["resource_ledger"] if row["resource_class"] == "Laptop")
    assert laptop["classification"] == "UNAVAILABLE"
    assert laptop["result"]["outcome"] == "WAITING_EXTERNAL"
    assert laptop["availability_reason"] == "awaiting_real_offline_laptop_execution"
    assert laptop["routing"]["selected_worker"] == "windows-runner"

    by_task: dict[str, list[dict]] = {}
    for row in result["resource_ledger"]:
        by_task.setdefault(row["task_id"], []).append(row)
    for task_id in ("P7-CLOUD-VERIFY", "P7-RESEARCH-STRATEGY", "P7-PAPER-PERFORMANCE"):
        rows = by_task[task_id]
        assert {row["role"] for row in rows} == {"producer", "verifier"}
        assert {row["classification"] for row in rows} == {"EXECUTED"}
        producer = next(row for row in rows if row["role"] == "producer")
        verifier = next(row for row in rows if row["role"] == "verifier")
        assert producer["worker_id"] != verifier["worker_id"]
        assert producer["lease_fencing"]["lease_id"] != verifier["lease_fencing"]["lease_id"]
        assert producer["lease_fencing"]["dispatch_id"] != verifier["lease_fencing"]["dispatch_id"]
        assert producer["latency_ms"] is not None and producer["latency_ms"] >= 0
        assert verifier["latency_ms"] is not None and verifier["latency_ms"] >= 0
        assert producer["verifier"]["worker_id"] == verifier["worker_id"]
        assert verifier["verifier"]["result"] == "success"

    classes = result["resource_classification"]
    assert classes["Laptop"]["classification"] == "UNAVAILABLE"
    assert classes["Internal Agent"]["classification"] == "EXECUTED"
    assert classes["Cloud/GitHub worker"]["classification"] == "EXECUTED"
    assert classes["DeepSeek/AI provider"]["classification"] == "UNAVAILABLE"


def test_prepare_without_courier_key_never_fabricates_hardware_dispatch(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("NEXUS_OFFLINE_COURIER_KEY", raising=False)
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(runner.executor, "execute", _fake_executor)
    monkeypatch.setattr(runner.phase7_e2e_proof, "build_proof", _fake_e2e)
    monkeypatch.setattr(runner.phase7_e2e_proof, "validate_proof", lambda proof, expected_source_sha: None)

    result = runner.prepare(SOURCE, tmp_path)
    runtime = json.loads((tmp_path / "agent-manager-runtime.json").read_text(encoding="utf-8"))
    laptop_task = am.task_index(runtime)["P7-LAPTOP-CANONICAL"]
    laptop_row = next(row for row in result["resource_ledger"] if row["resource_class"] == "Laptop")

    assert result["courier"]["status"] == "KEY_UNAVAILABLE"
    assert result["hardware_proof_complete"] is False
    assert "payload_sha256" not in result["courier"]
    assert laptop_task.get("dispatch_mode") is None
    assert laptop_task.get("offline_dispatch_digest") is None
    assert not (tmp_path / "courier" / "phase7-laptop-dispatch.json").exists()
    assert laptop_row["classification"] == "UNAVAILABLE"
    assert laptop_row["availability_reason"] == "missing_courier_key"
    assert laptop_row["result"]["outcome"] == "not_executed"
    assert result["resource_classification"]["Laptop"]["classification"] == "UNAVAILABLE"


def test_deepseek_missing_configuration_is_unavailable_and_routing_reports_unavailable(monkeypatch):
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    cfg = runner.load_runtime_template()
    cfg["resource_metrics"]["deepseek-bounded"]["available"] = False
    ledger: list[dict] = []

    status = runner._run_deepseek_advisory(cfg, SOURCE, ledger)

    assert status == {"status": "UNAVAILABLE", "reason": "missing_provider_configuration", "task_id": runner.DEEPSEEK_TASK_ID}
    assert len(ledger) == 1
    row = ledger[0]
    _assert_ledger_contract(row)
    assert row["classification"] == "UNAVAILABLE"
    assert row["resource_class"] == "DeepSeek/AI provider"
    assert row["routing"]["selected_worker"] is None
    assert row["routing"]["selected_observed"]["available"] is False
    assert row["availability_reason"] == "missing_provider_configuration"


def test_deepseek_real_config_executes_real_provider_lane_when_executor_succeeds(monkeypatch):
    monkeypatch.setenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-test-key")
    monkeypatch.setattr(runner.executor, "execute", _fake_executor)
    cfg = runner.load_runtime_template()
    cfg["resource_metrics"]["deepseek-bounded"]["available"] = True
    ledger: list[dict] = []

    status = runner._run_deepseek_advisory(cfg, SOURCE, ledger)

    assert status["status"] == "EXECUTED"
    assert status["model"] == "deepseek-test"
    assert status["cost_usd"] == 0.001
    row = ledger[0]
    _assert_ledger_contract(row)
    assert row["classification"] == "EXECUTED"
    assert row["result"]["outcome"] == "success"
    assert row["routing"]["selected_worker"] == "deepseek-bounded"
    assert row["budget_cost"]["provider_cost_usd"] == 0.001
    assert row["latency_ms"] is not None


def test_deepseek_provider_failure_is_unavailable_not_executed(monkeypatch):
    monkeypatch.setenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", "1")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "configured-test-key")

    def failed(payload: dict, transport: str) -> dict:
        result = _fake_executor(payload, transport)
        result["outcome"] = "failure"
        result["evidence"] = {"failure_class": "deepseek_provider_error", "provider": "deepseek"}
        return result

    monkeypatch.setattr(runner.executor, "execute", failed)
    cfg = runner.load_runtime_template()
    cfg["resource_metrics"]["deepseek-bounded"]["available"] = True
    ledger: list[dict] = []

    status = runner._run_deepseek_advisory(cfg, SOURCE, ledger)

    assert status["status"] == "UNAVAILABLE"
    assert status["reason"] == "deepseek_provider_error"
    assert ledger[0]["classification"] == "UNAVAILABLE"
    assert ledger[0]["result"]["failure_class"] == "deepseek_provider_error"
