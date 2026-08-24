from __future__ import annotations

from copy import deepcopy
import json

import pytest

import phase5_attempts as attempts
from nexus_verified_execution_cycle import VerifiedExecutionCycleError, run_cycle

SOURCE_SHA = "a" * 40


def success(_command: list[str]) -> dict:
    return {"returncode": 0, "stdout": "NEXUS integration registry: valid\n", "stderr": ""}


def test_real_cycle_binds_dispatch_result_evidence_and_independent_verifier(tmp_path) -> None:
    output = tmp_path / "cycle.json"
    ledger = run_cycle(source_sha=SOURCE_SHA, output_path=output, runner=success)

    assert ledger["schema_version"] == "nexus.verified-execution-cycle.v1"
    assert ledger["final_status"] == "VERIFIED"
    assert ledger["live_trading_authority"] is False
    assert ledger["source_revision"] == SOURCE_SHA
    assert len(ledger["source_sha"]) == 64
    assert ledger["dispatch"]["lease_id"] == ledger["producer_result"]["lease_id"]
    assert ledger["dispatch"]["attempt_id"] == ledger["verification_manifest"]["attempt_id"]
    assert ledger["producer_result"]["evidence"]["returncode"] == 0
    assert ledger["verification_manifest"]["decision"] == "pass"
    assert ledger["verification_manifest"]["producer"]["worker_id"] == "integration-producer"
    assert ledger["verification_manifest"]["verifier"]["worker_id"] == "integration-verifier"
    assert ledger["verification_manifest"]["producer"]["trust_domain"] != ledger["verification_manifest"]["verifier"]["trust_domain"]
    assert [item["classification"] for item in ledger["resource_utilization"]] == ["EXECUTED", "EXECUTED"]
    assert json.loads(output.read_text(encoding="utf-8")) == ledger


def test_ci_executes_the_real_bounded_registry_workload(tmp_path) -> None:
    ledger = run_cycle(source_sha=SOURCE_SHA, output_path=tmp_path / "real-cycle.json")
    evidence = ledger["producer_result"]["evidence"]
    assert evidence["returncode"] == 0
    assert "NEXUS integration registry: valid" in evidence["stdout"]
    assert ledger["verification_manifest"]["decision"] == "pass"


def test_failed_workload_never_becomes_verified(tmp_path) -> None:
    def failure(_command: list[str]) -> dict:
        return {"returncode": 1, "stdout": "", "stderr": "invalid registry"}

    with pytest.raises(VerifiedExecutionCycleError, match="rejected"):
        run_cycle(source_sha=SOURCE_SHA, output_path=tmp_path / "cycle.json", runner=failure)
    assert not (tmp_path / "cycle.json").exists()


def test_runner_schema_fails_closed(tmp_path) -> None:
    with pytest.raises(VerifiedExecutionCycleError, match="schema mismatch"):
        run_cycle(
            source_sha=SOURCE_SHA,
            output_path=tmp_path / "cycle.json",
            runner=lambda _command: {"returncode": 0},
        )


def test_source_sha_is_strict() -> None:
    with pytest.raises(VerifiedExecutionCycleError, match="source revision"):
        run_cycle(source_sha="not-a-sha", runner=success)


def test_existing_fence_contract_rejects_spoof_and_duplicate_conflict() -> None:
    task = {
        "mission_id": "m",
        "mission_revision": 1,
        "policy_version": "p",
        "id": "t",
        "spec_digest": "b" * 64,
        "authority": 1,
    }
    attempt = attempts.begin_attempt(
        task,
        worker_id="producer",
        lease_id="lease-current",
        source_sha="a" * 64,
        state_generation=1,
    )
    result = attempts.build_result(attempt, outcome="success", evidence={"ok": True})
    spoofed = deepcopy(result)
    spoofed["worker_id"] = "attacker"
    with pytest.raises(attempts.StaleAttempt):
        attempts.accept_result(task, spoofed)
    assert attempts.accept_result(task, result) is True
    assert attempts.accept_result(task, deepcopy(result)) is False
    conflicting = deepcopy(result)
    conflicting["evidence"] = {"ok": False}
    with pytest.raises(attempts.AttemptConflict):
        attempts.accept_result(task, conflicting)
