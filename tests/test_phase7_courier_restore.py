from __future__ import annotations

from pathlib import Path

import agent_manager as am
import offline_agent_courier as courier
import phase5_mission_contract as mission_contract
from scripts import phase7_proof_prepare as proof_runner


KEY = "phase7-restore-key-" + "x" * 40


def _fake_windows_result(payload: dict, transport: str) -> dict:
    assert transport == "windows"
    return {
        "schema_version": 2,
        "task_id": payload["task_id"],
        "lease_id": payload["lease_id"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
        "worker_id": payload["worker_id"],
        "transport": transport,
        "outcome": "success",
        "evidence": {"executor": "offline-restore-proof", "offline": True},
    }


def test_offline_result_can_be_imported_after_clean_supervisor_restore(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(courier.executor, "execute", _fake_windows_result)

    runtime = proof_runner.load_runtime_template()
    am.cycle(runtime)
    laptop = am.task_index(runtime)["P7-LAPTOP-CANONICAL"]
    assert laptop["status"] == "LEASED"
    assert laptop["assigned_worker"] == "windows-runner"

    runtime_path = tmp_path / "runtime.json"
    summary_path = tmp_path / "summary.json"
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(
        runtime,
        "P7-LAPTOP-CANONICAL",
        dispatch_path,
        runtime_path=runtime_path,
        summary_path=summary_path,
    )
    courier.execute_bundle(dispatch_path, result_path)

    fresh_template = proof_runner.load_runtime_template()
    restored = mission_contract.merge_compatible_runtime(fresh_template, runtime)
    restored_laptop = am.task_index(restored)["P7-LAPTOP-CANONICAL"]

    assert restored_laptop["dispatch_mode"] == "offline-courier"
    assert restored_laptop["offline_dispatch_digest"] == laptop["offline_dispatch_digest"]
    assert restored_laptop["offline_dispatch_bundle_created_at"] == laptop["offline_dispatch_bundle_created_at"]
    assert restored_laptop["external_wait_state"] == am.WAITING_EXTERNAL
    assert restored_laptop["dispatch_id"] == laptop["dispatch_id"]
    assert restored_laptop["lease_id"] == laptop["lease_id"]

    courier.import_result(
        restored,
        result_path,
        runtime_path=runtime_path,
        summary_path=summary_path,
    )
    imported = am.task_index(restored)["P7-LAPTOP-CANONICAL"]
    assert imported["status"] == "VERIFYING"
    assert imported["producer"] == "windows-runner"
    assert imported["verifier"] == "qa-verifier-agent"
    assert imported["assigned_worker"] == "qa-verifier-agent"
    assert imported["offline_result_bundle_ingested"] is True
    assert imported["external_wait_state"] == "COMPLETED"
