from __future__ import annotations

import json
from copy import deepcopy
from datetime import timedelta

import pytest

import agent_manager as am
import agent_manager_runner as runner
import agent_transport as at
import offline_agent_courier as courier


KEY = "k" * 48


def leased_task(*, lease_id: str = "lease-offline-1"):
    return {
        "id": "P4-DATA-001",
        "title": "offline canonical data validation",
        "phase": 4,
        "gate": 3,
        "status": "LEASED",
        "priority": 88,
        "dependencies": [],
        "required_capabilities": ["data_validation"],
        "preferred_resources": ["windows-local"],
        "authority": 1,
        "acceptance": ["canonical data validated"],
        "assigned_worker": "windows-runner",
        "producer": "windows-runner",
        "lease_id": lease_id,
        "leased_at": am.iso(),
        "heartbeat_at": am.iso(),
        "lease_expires_at": am.iso(am.utcnow() + timedelta(minutes=5)),
        "attempt": 1,
    }


def config(task=None):
    return {
        "schema_version": 1,
        "phase": 4,
        "policy": {
            "max_parallel_tasks": 4,
            "offline_courier_workers": ["windows-runner"],
            "offline_courier_lease_minutes": 120,
        },
        "workers": [
            {
                "id": "windows-runner",
                "capabilities": ["data_validation"],
                "resources": ["windows-local"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
                "max_concurrent_tasks": 1,
            },
            {
                "id": "qa-verifier-agent",
                "capabilities": ["data_validation"],
                "resources": ["github-cloud"],
                "authority_max": 3,
                "enabled": True,
                "verifier": True,
                "max_concurrent_tasks": 1,
            },
        ],
        "tasks": [task or leased_task()],
    }


def prepare(monkeypatch, tmp_path):
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.setattr(am, "EVENT_PATH", tmp_path / "events.jsonl")
    return tmp_path / "runtime.json", tmp_path / "summary.json"


def fake_success_result(payload, transport):
    return {
        "schema_version": 2,
        "task_id": payload["task_id"],
        "lease_id": payload["lease_id"],
        "correlation_id": payload["correlation_id"],
        "dispatch_id": payload["dispatch_id"],
        "worker_id": payload["worker_id"],
        "transport": transport,
        "outcome": "success",
        "evidence": {},
    }


def test_github_transport_skips_offline_courier_worker(monkeypatch):
    cfg = config()
    calls = []
    monkeypatch.setattr(at, "dispatch_task", lambda task, ref: calls.append(task["id"]))
    assert at.dispatch_pending(cfg, ref="main") == 0
    assert calls == []
    assert cfg["tasks"][0]["status"] == "LEASED"


def test_export_is_fenced_hmac_bound_and_uses_bounded_offline_lease(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    am.atomic_json(runtime, cfg)
    output = tmp_path / "dispatch.json"

    bundle = courier.export_task(cfg, "P4-DATA-001", output, runtime_path=runtime, summary_path=summary)
    task = cfg["tasks"][0]
    assert bundle["kind"] == courier.DISPATCH_KIND
    assert bundle["payload"]["dispatch_id"] == at.dispatch_id_for(task)
    assert task["status"] == "RUNNING"
    assert task["dispatch_mode"] == "offline-courier"
    assert task["heartbeat_at"] is None
    assert task["offline_dispatch_digest"] == bundle["payload_sha256"]
    expiry = am.parse_time(task["lease_expires_at"])
    assert expiry is not None
    assert timedelta(minutes=115) < expiry - am.utcnow() <= timedelta(minutes=120)


def test_tampered_dispatch_bundle_is_rejected(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    output = tmp_path / "dispatch.json"
    courier.export_task(cfg, "P4-DATA-001", output, runtime_path=runtime, summary_path=summary)
    data = json.loads(output.read_text(encoding="utf-8"))
    data["payload"]["authority"] = 3
    output.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="signature mismatch"):
        courier.execute_bundle(output, tmp_path / "result.json")


def test_offline_execute_and_import_enters_independent_verification(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(cfg, "P4-DATA-001", dispatch_path, runtime_path=runtime, summary_path=summary)

    def fake_execute(payload, transport):
        assert transport == "windows"
        result = fake_success_result(payload, transport)
        result["evidence"] = {"executor": "offline-test", "canonical": True}
        return result

    monkeypatch.setattr(courier.executor, "execute", fake_execute)
    result_bundle = courier.execute_bundle(dispatch_path, result_path)
    assert result_bundle["result"]["outcome"] == "success"

    courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)
    task = cfg["tasks"][0]
    assert task["status"] == "VERIFYING"
    assert task["producer"] == "windows-runner"
    assert task["verifier"] == "qa-verifier-agent"
    assert task["assigned_worker"] == "qa-verifier-agent"
    assert task["offline_result_bundle_ingested"] is True
    assert task["offline_result_bundle_digest"] == result_bundle["result_sha256"]


def test_replayed_result_bundle_is_rejected_after_first_import(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(cfg, "P4-DATA-001", dispatch_path, runtime_path=runtime, summary_path=summary)
    monkeypatch.setattr(courier.executor, "execute", fake_success_result)
    courier.execute_bundle(dispatch_path, result_path)

    courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)
    task = cfg["tasks"][0]
    verifier_lease = task["lease_id"]
    assert task["status"] == "VERIFYING"

    with pytest.raises(ValueError, match="stale or mismatched task result"):
        courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)
    assert task["status"] == "VERIFYING"
    assert task["lease_id"] == verifier_lease


def test_validly_sealed_result_for_wrong_worker_is_rejected(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(cfg, "P4-DATA-001", dispatch_path, runtime_path=runtime, summary_path=summary)
    monkeypatch.setattr(courier.executor, "execute", fake_success_result)
    bundle = courier.execute_bundle(dispatch_path, result_path)

    forged_result = deepcopy(bundle["result"])
    forged_result["worker_id"] = "qa-verifier-agent"
    forged_unsigned = {
        "schema_version": 1,
        "kind": courier.RESULT_KIND,
        "created_at": bundle["created_at"],
        "source_dispatch_sha256": bundle["source_dispatch_sha256"],
        "result_sha256": courier._digest(forged_result),
        "result": forged_result,
    }
    result_path.write_text(json.dumps(courier._seal(forged_unsigned)), encoding="utf-8")

    with pytest.raises(ValueError, match="worker does not own lease"):
        courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)
    assert cfg["tasks"][0]["status"] == "RUNNING"


def test_stale_result_from_previous_lease_is_rejected(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(cfg, "P4-DATA-001", dispatch_path, runtime_path=runtime, summary_path=summary)
    monkeypatch.setattr(courier.executor, "execute", fake_success_result)
    courier.execute_bundle(dispatch_path, result_path)

    task = cfg["tasks"][0]
    task["lease_id"] = "new-lease"
    task["attempt"] = 2
    task["dispatch_id"] = at.dispatch_id_for(task)
    task["offline_dispatch_digest"] = "0" * 64
    with pytest.raises(ValueError, match="not bound to current dispatch"):
        courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)


def test_result_after_offline_lease_expiry_is_rejected(monkeypatch, tmp_path):
    runtime, summary = prepare(monkeypatch, tmp_path)
    cfg = config()
    dispatch_path = tmp_path / "dispatch.json"
    result_path = tmp_path / "result.json"
    courier.export_task(cfg, "P4-DATA-001", dispatch_path, runtime_path=runtime, summary_path=summary)
    monkeypatch.setattr(courier.executor, "execute", fake_success_result)
    courier.execute_bundle(dispatch_path, result_path)
    cfg["tasks"][0]["lease_expires_at"] = am.iso(am.utcnow() - timedelta(seconds=1))
    with pytest.raises(ValueError, match="after lease expiry"):
        courier.import_result(cfg, result_path, runtime_path=runtime, summary_path=summary)


def test_runtime_merge_preserves_offline_courier_evidence():
    template = config()
    runtime_cfg = deepcopy(template)
    task = runtime_cfg["tasks"][0]
    task.update(
        {
            "status": "RUNNING",
            "dispatch_mode": "offline-courier",
            "offline_dispatch_digest": "a" * 64,
            "offline_dispatch_bundle_created_at": "2026-08-18T12:00:00+00:00",
            "offline_result_bundle_ingested": False,
        }
    )
    merged = runner.merge_definition(template, runtime_cfg)
    restored = merged["tasks"][0]
    assert restored["dispatch_mode"] == "offline-courier"
    assert restored["offline_dispatch_digest"] == "a" * 64
    assert restored["offline_result_bundle_ingested"] is False