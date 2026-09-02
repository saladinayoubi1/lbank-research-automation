from __future__ import annotations

import sys

import base64
import json

import pytest

from scripts import agent_task_executor as executor


def payload(task_id: str, transport: str, *, phase: int = 7, authority: int = 1) -> dict:
    return {
        "schema_version": 2,
        "task_id": task_id,
        "lease_id": f"lease-{task_id}",
        "correlation_id": f"corr-{task_id}",
        "dispatch_id": f"dispatch-{task_id}",
        "worker_id": "windows-runner" if transport == "windows" else "cloud-worker",
        "transport": transport,
        "phase": phase,
        "gate": 0,
        "title": task_id,
        "required_capabilities": ["integration_tests"],
        "acceptance": ["real bounded workload result"],
        "authority": authority,
        "attempt": 1,
    }


def fake_success(cmd: list[str], timeout: int = 600) -> dict:
    return {"ok": True, "returncode": 0, "stdout": "3 passed", "stderr": ""}


def test_laptop_canonical_executes_only_offline_windows_suite(monkeypatch) -> None:
    calls = []

    def fake(cmd: list[str], timeout: int = 600) -> dict:
        calls.append((cmd, timeout))
        return fake_success(cmd, timeout)

    monkeypatch.setattr(executor, "run", fake)
    result = executor.execute(payload("P7-LAPTOP-CANONICAL", "windows"), "windows")

    assert result["outcome"] == "success"
    evidence = result["evidence"]
    assert evidence["workload_id"] == "P7-LAPTOP-CANONICAL"
    assert evidence["offline_capable"] is True
    assert evidence["network_required"] is False
    assert evidence["transport"] == "windows"
    assert evidence["suite"] == [
        "tests/test_phase5_data_binding.py",
        "tests/test_canonical_backtest_boundary.py",
        "tests/test_product_offline_runtime.py",
    ]
    assert calls == [([sys.executable, "-m", "pytest", "-q", *evidence["suite"]], 900)]


def test_laptop_canonical_refuses_cloud_substitution_without_execution(monkeypatch) -> None:
    monkeypatch.setattr(executor, "run", lambda *_args, **_kwargs: pytest.fail("must not execute"))
    result = executor.execute(payload("P7-LAPTOP-CANONICAL", "github-cloud"), "github-cloud")
    assert result["outcome"] == "failure"
    assert result["evidence"]["failure_class"] == "workload_transport_mismatch"
    assert result["evidence"]["allowed_transports"] == ["windows"]


def test_cloud_verifier_executes_resource_transport_projection_suite(monkeypatch) -> None:
    seen = []

    def fake(cmd: list[str], timeout: int = 600) -> dict:
        seen.extend(cmd)
        return fake_success(cmd, timeout)

    monkeypatch.setattr(executor, "run", fake)
    result = executor.execute(payload("P7-CLOUD-VERIFY", "github-cloud"), "github-cloud")
    assert result["outcome"] == "success"
    assert result["evidence"]["suite"] == [
        "tests/test_agent_transport.py",
        "tests/test_phase7_resource_manager.py",
        "tests/test_phase7_mission_projection.py",
    ]
    assert "tests/test_phase7_resource_manager.py" in seen


def test_research_and_paper_workloads_are_bounded_cloud_suites(monkeypatch) -> None:
    monkeypatch.setattr(executor, "run", fake_success)
    research = executor.execute(payload("P7-RESEARCH-STRATEGY", "github-cloud"), "github-cloud")
    paper = executor.execute(payload("P7-PAPER-PERFORMANCE", "github-cloud"), "github-cloud")
    assert research["outcome"] == "success"
    assert research["evidence"]["suite"] == [
        "tests/test_phase5_strategy_factory.py",
        "tests/test_phase6_research_pipeline.py",
        "tests/test_downstream_provenance_boundary.py",
    ]
    assert paper["outcome"] == "success"
    assert paper["evidence"]["suite"] == [
        "tests/test_deterministic_risk.py",
        "tests/test_paper_execution.py",
        "tests/test_paper_event_store.py",
        "tests/test_performance_metrics.py",
        "tests/test_phase7_e2e_proof.py",
    ]


def test_phase7_identifier_requires_phase7_and_unknown_task_still_refuses(monkeypatch) -> None:
    monkeypatch.setattr(executor, "run", lambda *_args, **_kwargs: pytest.fail("must not execute"))
    wrong_phase = executor.execute(payload("P7-CLOUD-VERIFY", "github-cloud", phase=6), "github-cloud")
    assert wrong_phase["outcome"] == "failure"
    assert wrong_phase["evidence"]["failure_class"] == "workload_phase_mismatch"

    unknown = executor.execute(payload("P7-UNKNOWN", "github-cloud"), "github-cloud")
    assert unknown["outcome"] == "failure"
    assert unknown["evidence"]["failure_class"] == "specialized_reasoning_provider_required"


def test_decode_payload_still_rejects_l4() -> None:
    raw = json.dumps(payload("P7-CLOUD-VERIFY", "github-cloud", authority=4), separators=(",", ":")).encode()
    encoded = base64.b64encode(raw).decode("ascii")
    with pytest.raises(ValueError, match="L4"):
        executor.decode_payload(encoded)
