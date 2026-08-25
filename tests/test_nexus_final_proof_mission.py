from copy import deepcopy
from pathlib import Path

import pytest

import nexus_final_proof_mission as proof

SHA = "a" * 40


def _supervisor():
    return {"source_sha": SHA, "tasks": [{"task_id": "strategy-1"}]}


def _resources():
    executed = {
        "state": "EXECUTED", "source_sha": SHA, "task_id": "task-1",
        "lease_id": "lease-1", "result_digest": "r" * 64,
        "evidence_digest": "e" * 64, "verifier_digest": "v" * 64,
    }
    return [
        {"resource": "internal_agents", **executed},
        {"resource": "cloud_verifier", **executed, "task_id": "verify-1"},
        {"resource": "deepseek", "state": "UNAVAILABLE", "source_sha": SHA,
         "reason_code": "provider_not_configured"},
        {"resource": "windows_laptop", **executed, "task_id": "windows-task-1"},
    ]


def _bundle(monkeypatch):
    monkeypatch.setattr(proof, "verify_ledger", lambda _value: {
        "decision": "pass", "verification_digest": "s" * 64,
    })
    return proof.build_unsigned_bundle(
        source_sha=SHA,
        supervisor_ledger=_supervisor(),
        mission_control_projection={
            "paper_only": True, "live_trading_authority": False,
            "supervisor_verification_digest": "s" * 64,
        },
        scheduler_snapshot={
            "source_sha": SHA, "ready_unassigned_count": 0,
            "idle_with_executable_work_count": 0,
        },
        resource_utilization=_resources(),
    )


def test_fixed_sha_complete_bundle_verifies_and_persists(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(monkeypatch)
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "VERIFIED"
    assert result["checks"]["deepseek_truthful"] is True
    assert result["checks"]["windows_truthful"] is True
    assert result["checks"]["windows_physical_execution"] is True
    saved = proof.save_verified_bundle(tmp_path / "proof.json", bundle)
    assert saved["verification"]["decision"] == "VERIFIED"
    assert (tmp_path / "proof.json").is_file()


@pytest.mark.parametrize("mutation", ["live", "spoof", "idle", "memory", "deepseek"])
def test_authority_spoof_idle_and_false_resource_claims_reject(monkeypatch, mutation) -> None:
    bundle = _bundle(monkeypatch)
    if mutation == "live":
        bundle["live_trading_authority"] = True
    elif mutation == "spoof":
        bundle["resource_utilization"][0]["lease_id"] = ""
    elif mutation == "idle":
        bundle["scheduler_snapshot"]["ready_unassigned_count"] = 1
    elif mutation == "memory":
        bundle["project_memory_projection"]["observed_main_sha"] = "b" * 40
    else:
        bundle["resource_utilization"][2] = {
            "resource": "deepseek", "state": "EXECUTED", "source_sha": SHA,
        }
    assert proof.verify_final_proof(bundle)["decision"] == "REJECTED"


def test_duplicate_or_missing_resources_reject(monkeypatch) -> None:
    bundle = _bundle(monkeypatch)
    bundle["resource_utilization"][3]["resource"] = "internal_agents"
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "REJECTED"
    assert result["checks"]["required_resources_declared"] is False


@pytest.mark.parametrize("state", ["BLOCKED", "UNAVAILABLE"])
def test_missing_physical_windows_execution_rejects(monkeypatch, state) -> None:
    bundle = _bundle(monkeypatch)
    bundle["resource_utilization"][3] = {
        "resource": "windows_laptop",
        "state": state,
        "source_sha": SHA,
        "reason_code": "physical_evidence_pending",
    }
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "REJECTED"
    assert result["checks"]["windows_truthful"] is True
    assert result["checks"]["windows_physical_execution"] is False


@pytest.mark.parametrize(
    "field", ["result_digest", "evidence_digest", "verifier_digest"]
)
def test_noncanonical_execution_digest_rejects(monkeypatch, field) -> None:
    bundle = _bundle(monkeypatch)
    bundle["resource_utilization"][0][field] = "present-but-not-a-digest"
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "REJECTED"


def test_invalid_sha_and_rejected_supervisor_fail_closed(monkeypatch) -> None:
    with pytest.raises(proof.FinalProofMissionError, match="source_sha"):
        proof.build_unsigned_bundle(
            source_sha="main", supervisor_ledger={}, mission_control_projection={},
            scheduler_snapshot={}, resource_utilization=[],
        )
    monkeypatch.setattr(proof, "verify_ledger", lambda _value: {"decision": "reject"})
    bundle = proof.build_unsigned_bundle(
        source_sha=SHA, supervisor_ledger=_supervisor(), mission_control_projection={},
        scheduler_snapshot={}, resource_utilization=_resources(),
    )
    assert proof.verify_final_proof(bundle)["decision"] == "REJECTED"
from copy import deepcopy
from pathlib import Path

import pytest

import nexus_final_proof_mission as proof

SHA = "a" * 40


def _supervisor():
    return {"source_sha": SHA, "tasks": [{"task_id": "strategy-1"}]}


def _resources():
    executed = {
        "state": "EXECUTED", "source_sha": SHA, "task_id": "task-1",
        "lease_id": "lease-1", "result_digest": "r" * 64,
        "evidence_digest": "e" * 64, "verifier_digest": "v" * 64,
    }
    return [
        {"resource": "internal_agents", **executed},
        {"resource": "cloud_verifier", **executed, "task_id": "verify-1"},
        {"resource": "deepseek", "state": "UNAVAILABLE", "source_sha": SHA,
         "reason_code": "provider_not_configured"},
        {"resource": "windows_laptop", "state": "BLOCKED", "source_sha": SHA,
         "reason_code": "physical_evidence_pending"},
    ]


def _bundle(monkeypatch):
    monkeypatch.setattr(proof, "verify_ledger", lambda _value: {
        "decision": "pass", "verification_digest": "s" * 64,
    })
    return proof.build_unsigned_bundle(
        source_sha=SHA,
        supervisor_ledger=_supervisor(),
        mission_control_projection={
            "paper_only": True, "live_trading_authority": False,
            "supervisor_verification_digest": "s" * 64,
        },
        scheduler_snapshot={
            "source_sha": SHA, "ready_unassigned_count": 0,
            "idle_with_executable_work_count": 0,
        },
        resource_utilization=_resources(),
    )


def test_fixed_sha_complete_bundle_verifies_and_persists(tmp_path: Path, monkeypatch) -> None:
    bundle = _bundle(monkeypatch)
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "VERIFIED"
    assert result["checks"]["deepseek_truthful"] is True
    assert result["checks"]["windows_truthful"] is True
    saved = proof.save_verified_bundle(tmp_path / "proof.json", bundle)
    assert saved["verification"]["decision"] == "VERIFIED"
    assert (tmp_path / "proof.json").is_file()


@pytest.mark.parametrize("mutation", ["live", "spoof", "idle", "memory", "deepseek"])
def test_authority_spoof_idle_and_false_resource_claims_reject(monkeypatch, mutation) -> None:
    bundle = _bundle(monkeypatch)
    if mutation == "live":
        bundle["live_trading_authority"] = True
    elif mutation == "spoof":
        bundle["resource_utilization"][0]["lease_id"] = ""
    elif mutation == "idle":
        bundle["scheduler_snapshot"]["ready_unassigned_count"] = 1
    elif mutation == "memory":
        bundle["project_memory_projection"]["observed_main_sha"] = "b" * 40
    else:
        bundle["resource_utilization"][2] = {
            "resource": "deepseek", "state": "EXECUTED", "source_sha": SHA,
        }
    assert proof.verify_final_proof(bundle)["decision"] == "REJECTED"


def test_duplicate_or_missing_resources_reject(monkeypatch) -> None:
    bundle = _bundle(monkeypatch)
    bundle["resource_utilization"][3]["resource"] = "internal_agents"
    result = proof.verify_final_proof(bundle)
    assert result["decision"] == "REJECTED"
    assert result["checks"]["required_resources_declared"] is False


def test_invalid_sha_and_rejected_supervisor_fail_closed(monkeypatch) -> None:
    with pytest.raises(proof.FinalProofMissionError, match="source_sha"):
        proof.build_unsigned_bundle(
            source_sha="main", supervisor_ledger={}, mission_control_projection={},
            scheduler_snapshot={}, resource_utilization=[],
        )
    monkeypatch.setattr(proof, "verify_ledger", lambda _value: {"decision": "reject"})
    bundle = proof.build_unsigned_bundle(
        source_sha=SHA, supervisor_ledger=_supervisor(), mission_control_projection={},
        scheduler_snapshot={}, resource_utilization=_resources(),
    )
    assert proof.verify_final_proof(bundle)["decision"] == "REJECTED"
