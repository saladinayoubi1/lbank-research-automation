from __future__ import annotations

import json
from pathlib import Path

import pytest

import phase7_offline_network_proof as proof

SOURCE = "a" * 40
SESSION = "p7-20260818T200000Z-deadbeef"


def _result(tmp_path: Path) -> Path:
    path = tmp_path / "result.json"
    path.write_text('{"result":"ok"}\n', encoding="utf-8")
    return path


def _value(result: Path) -> dict:
    return {
        "schema_version": proof.SCHEMA,
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
        "result_sha256": proof.sha256_file(result),
        "observation_method": proof.OBSERVATION_METHOD,
    }


def _write(tmp_path: Path, value: dict) -> Path:
    path = tmp_path / "offline-network-proof.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_valid_offline_network_proof_binds_reboot_network_and_result(tmp_path: Path):
    result = _result(tmp_path)
    path = _write(tmp_path, _value(result))
    evidence = proof.validate_offline_network_proof(
        path,
        result,
        expected_source_sha=SOURCE,
        expected_session_id=SESSION,
    )
    assert evidence["reboot_after_prepare"] is True
    assert evidence["internet_unavailable_pre"] is True
    assert evidence["internet_unavailable_post"] is True
    assert evidence["result_sha256"] == proof.sha256_file(result)
    assert evidence["proof_sha256"] == proof.sha256_file(path)
    assert set(evidence["observations"]) == {"pre_execution", "post_execution"}


def test_reachable_external_target_rejects_offline_claim(tmp_path: Path):
    result = _result(tmp_path)
    value = _value(result)
    value["pre_execution"]["targets"][0]["reachable"] = True
    path = _write(tmp_path, value)
    with pytest.raises(proof.OfflineNetworkProofError, match="reachable external network"):
        proof.validate_offline_network_proof(path, result, expected_source_sha=SOURCE)


def test_missing_reboot_rejects_hardware_proof(tmp_path: Path):
    result = _result(tmp_path)
    value = _value(result)
    value["boot_time_utc"] = "2026-08-18T19:59:00Z"
    path = _write(tmp_path, value)
    with pytest.raises(proof.OfflineNetworkProofError, match="reboot after preparation"):
        proof.validate_offline_network_proof(path, result, expected_source_sha=SOURCE)


def test_result_tamper_after_offline_execution_rejects_proof(tmp_path: Path):
    result = _result(tmp_path)
    path = _write(tmp_path, _value(result))
    result.write_text('{"result":"tampered"}\n', encoding="utf-8")
    with pytest.raises(proof.OfflineNetworkProofError, match="not bound to returned"):
        proof.validate_offline_network_proof(path, result, expected_source_sha=SOURCE)


def test_duplicate_network_targets_are_not_independent(tmp_path: Path):
    result = _result(tmp_path)
    value = _value(result)
    value["post_execution"]["targets"][1] = dict(value["post_execution"]["targets"][0])
    path = _write(tmp_path, value)
    with pytest.raises(proof.OfflineNetworkProofError, match="must be independent"):
        proof.validate_offline_network_proof(path, result, expected_source_sha=SOURCE)
