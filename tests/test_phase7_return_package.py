from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import offline_agent_courier as courier
import phase7_e2e_proof
import phase7_offline_network_proof as network_proof
from scripts import phase7_proof_complete as secure_completion
from scripts import phase7_proof_prepare as prepare
from scripts import phase7_return_package as package

SOURCE = "a" * 40
SESSION = "p7-20260818T200000Z-deadbeef"
KEY = "phase7-return-package-key-" + "x" * 40


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
        evidence = {"executor": "return-package-test", "workload_id": payload["task_id"]}
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


def _network(result: Path) -> dict:
    return {
        "schema_version": network_proof.SCHEMA,
        "session_id": SESSION,
        "source_sha": SOURCE,
        "prepared_at": "2026-08-18T20:00:00Z",
        "boot_time_utc": "2026-08-18T20:01:00Z",
        "reboot_after_prepare": True,
        "pre_execution": {
            "checked_at": "2026-08-18T20:02:00Z",
            "internet_unavailable": True,
            "targets": [
                {"host": "api.github.com", "port": 443, "reachable": False, "error": "offline"},
                {"host": "1.1.1.1", "port": 443, "reachable": False, "error": "offline"},
            ],
        },
        "execution_started_at": "2026-08-18T20:03:00Z",
        "execution_finished_at": "2026-08-18T20:04:00Z",
        "post_execution": {
            "checked_at": "2026-08-18T20:05:00Z",
            "internet_unavailable": True,
            "targets": [
                {"host": "api.github.com", "port": 443, "reachable": False, "error": "offline"},
                {"host": "1.1.1.1", "port": 443, "reachable": False, "error": "offline"},
            ],
        },
        "result_sha256": network_proof.sha256_file(result),
        "observation_method": network_proof.OBSERVATION_METHOD,
    }


def _build_package(monkeypatch, tmp_path: Path) -> Path:
    artifact = tmp_path / "artifact"
    monkeypatch.setenv(courier.KEY_ENV, KEY)
    monkeypatch.delenv("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(prepare.executor, "execute", _executor)
    monkeypatch.setattr(prepare.phase7_e2e_proof, "build_proof", _fake_e2e)
    prepare.prepare(SOURCE, artifact)

    returned = tmp_path / "phase7-laptop-result.json"
    monkeypatch.setattr(courier.executor, "execute", _executor)
    courier.execute_bundle(artifact / "courier/phase7-laptop-dispatch.json", returned)

    root = tmp_path / "package"
    for relative in package.PREPARED_FILES:
        source_relative = relative.removeprefix("prepared/")
        src = artifact / source_relative
        dst = root / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())
    result_dst = root / "returned/phase7-laptop-result.json"
    result_dst.parent.mkdir(parents=True, exist_ok=True)
    result_dst.write_bytes(returned.read_bytes())
    network_dst = root / "returned/offline-network-proof.json"
    network_dst.write_text(json.dumps(_network(result_dst)), encoding="utf-8")

    file_hashes = {
        relative: package._sha256(root / relative)
        for relative in sorted(package.PAYLOAD_FILES)
    }
    payload = {
        "schema_version": package.SCHEMA,
        "session_id": SESSION,
        "repository": package.REPO,
        "source_sha": SOURCE,
        "proof_run_id": 12345,
        "prepared_artifact_name": f"nexus-phase7-proof-{SOURCE}",
        "created_at": "2026-08-18T20:06:00Z",
        "files": file_hashes,
    }
    payload["package_sha256"] = hashlib.sha256(package._canonical(payload)).hexdigest()
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    return root


def test_valid_return_package_is_exact_source_data_only_and_offline_bound(monkeypatch, tmp_path: Path):
    root = _build_package(monkeypatch, tmp_path)
    result = package.validate_package(root, expected_source_sha=SOURCE)
    assert result["session_id"] == SESSION
    assert result["source_sha"] == SOURCE
    assert result["proof_run_id"] == 12345
    assert result["reboot_after_prepare"] is True
    assert result["internet_unavailable_pre"] is True
    assert result["internet_unavailable_post"] is True
    assert Path(result["prepared_dir"]).is_dir()
    assert Path(result["returned_result"]).is_file()


def test_extra_file_rejects_data_only_package(monkeypatch, tmp_path: Path):
    root = _build_package(monkeypatch, tmp_path)
    (root / "unexpected.txt").write_text("no", encoding="utf-8")
    with pytest.raises(package.Phase7ReturnPackageError, match="file set mismatch"):
        package.validate_package(root, expected_source_sha=SOURCE)


def test_manifest_tamper_rejects_package(monkeypatch, tmp_path: Path):
    root = _build_package(monkeypatch, tmp_path)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["returned/phase7-laptop-result.json"] = "0" * 64
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(package.Phase7ReturnPackageError, match="digest mismatch"):
        package.validate_package(root, expected_source_sha=SOURCE)


def test_returned_result_worker_spoof_rejects_before_secret_use(monkeypatch, tmp_path: Path):
    root = _build_package(monkeypatch, tmp_path)
    path = root / "returned/phase7-laptop-result.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    value["result"]["worker_id"] = "cloud-worker"
    path.write_text(json.dumps(value), encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["files"]["returned/phase7-laptop-result.json"] = package._sha256(path)
    package_payload = {key: manifest[key] for key in manifest if key != "package_sha256"}
    manifest["package_sha256"] = hashlib.sha256(package._canonical(package_payload)).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(package.Phase7ReturnPackageError, match="worker/transport"):
        package.validate_package(root, expected_source_sha=SOURCE)


def test_source_mismatch_rejects_return_package(monkeypatch, tmp_path: Path):
    root = _build_package(monkeypatch, tmp_path)
    with pytest.raises(package.Phase7ReturnPackageError, match="expected trusted source"):
        package.validate_package(root, expected_source_sha="b" * 40)
