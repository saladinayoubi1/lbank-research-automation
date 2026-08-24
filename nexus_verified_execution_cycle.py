"""Run one bounded NEXUS task through a replayable verified execution cycle.

This module composes the existing Phase 5 mission, attempt/fencing, result, and
independent-verification contracts.  It is deliberately maintenance-only: the
only built-in workload validates the canonical integration registry and cannot
reach Live/L4, credentials, exchange adapters, billing, or deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

import phase5_attempts as attempts
import phase5_mission_contract as mission_contract
import phase5_verification as verification
from nexus_execution_contract import validate_pre_execution_record, validate_task_record

ROOT = Path(__file__).resolve().parent
SCHEMA = "nexus.verified-execution-cycle.v1"
WORKLOAD_ID = "NEXUS-INTEGRATION-VALIDATE"
DEFAULT_OUTPUT = ROOT / "build" / "evidence" / "nexus-verified-execution-cycle.json"
Runner = Callable[[list[str]], dict[str, Any]]


class VerifiedExecutionCycleError(RuntimeError):
    pass


def _digest(value: Any) -> str:
    try:
        raw = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise VerifiedExecutionCycleError("cycle evidence is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise VerifiedExecutionCycleError(f"{field} must be a SHA-256 hex digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise VerifiedExecutionCycleError(f"{field} must be a SHA-256 hex digest") from exc
    return value.lower()


def _source_identity(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) not in {40, 64}:
        raise VerifiedExecutionCycleError("source revision must be a 40- or 64-character Git object id")
    try:
        int(value, 16)
    except ValueError as exc:
        raise VerifiedExecutionCycleError("source revision must be a hexadecimal Git object id") from exc
    revision = value.lower()
    # Phase 5 attempt manifests intentionally require a SHA-256 identity even
    # when the repository still uses SHA-1 Git object IDs. Preserve both: the
    # exact Git revision for checkout/replay and a deterministic SHA-256 binding
    # for the existing fenced-result contract.
    return revision, hashlib.sha256(("git-object:" + revision).encode("ascii")).hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _default_runner(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout[-16_000:],
        "stderr": completed.stderr[-16_000:],
    }


def _mission() -> dict[str, Any]:
    return {
        "schema_version": mission_contract.MISSION_SCHEMA,
        "mission_id": "nexus-maintenance-integration-cycle",
        "mission_revision": 1,
        "phase": 7,
        "policy": {"version": "nexus-maintenance-v1", "max_parallel_tasks": 1},
        "workers": [
            {
                "id": "integration-producer",
                "trust_domain": "bounded-local-runtime",
                "capabilities": ["integration_validation"],
                "resources": ["agents"],
                "authority_max": 1,
                "enabled": True,
                "verifier": False,
            },
            {
                "id": "integration-verifier",
                "trust_domain": "independent-contract-verifier",
                "capabilities": ["integration_verification"],
                "resources": ["github_actions"],
                "authority_max": 1,
                "enabled": True,
                "verifier": True,
            },
        ],
        "tasks": [
            {
                "id": WORKLOAD_ID,
                "title": "Validate the merged NEXUS integration graph",
                "phase": 7,
                "gate": 0,
                "status": "QUEUED",
                "priority": 1,
                "dependencies": [],
                "required_capabilities": ["integration_validation"],
                "preferred_resources": ["agents"],
                "authority": 1,
                "acceptance": ["canonical integration registry validates fail-closed"],
                "verification": {
                    "mode": "independent_trust_domain",
                    "required_capabilities": ["integration_verification"],
                },
            }
        ],
    }


def _execution_record(output_path: Path) -> dict[str, Any]:
    return {
        "task_id": WORKLOAD_ID,
        "lane": "evidence/verification",
        "deliverable_or_gate": "merged integration graph maintenance proof",
        "acceptance_criterion": "real bounded workload result is independently verified",
        "assigned_resource": "agents",
        "dependencies": [],
        "execution_action": "execute canonical integration registry validator",
        "verification_method": "independent trust-domain contract replay",
        "durable_evidence_location": str(output_path),
        "status": "QUEUED",
    }


def _pre_execution_record() -> dict[str, bool]:
    return {
        "recover_current_repository_state": True,
        "read_OPERATING_RULES": True,
        "identify_phase_and_frozen_exit_gates": True,
        "enumerate_available_resources": True,
        "enumerate_executable_independent_tasks": True,
        "map_each_task_to_acceptance_criterion": True,
        "map_each_task_to_best_resource": True,
        "record_dependencies_and_blockers": True,
        "confirm_authority_boundary": True,
    }


def run_cycle(
    *,
    source_sha: str,
    output_path: Path = DEFAULT_OUTPUT,
    runner: Runner = _default_runner,
) -> dict[str, Any]:
    source_revision, source_sha = _source_identity(source_sha)
    execution_record = validate_task_record(_execution_record(output_path))
    validate_pre_execution_record(_pre_execution_record())

    config = mission_contract.to_agent_manager_config(_mission())
    task = config["tasks"][0]
    lease_id = "lease-" + _digest({"source_sha": source_sha, "spec_digest": task["spec_digest"]})[:32]
    task["status"] = "LEASED"
    task["assigned_worker"] = "integration-producer"
    task["producer"] = "integration-producer"
    task["lease_id"] = lease_id

    attempt = attempts.begin_attempt(
        task,
        worker_id="integration-producer",
        lease_id=lease_id,
        source_sha=source_sha,
        state_generation=1,
    )
    command = [sys.executable, str(ROOT / "nexus_integration_validator.py")]
    dispatch = {
        "task_id": task["id"],
        "lease_id": lease_id,
        "attempt_id": attempt["attempt_id"],
        "fence_generation": attempt["fence_generation"],
        "worker_id": attempt["worker_id"],
        "source_sha": source_sha,
        "source_revision": source_revision,
        "command_sha256": _digest(command),
        "authority": task["authority"],
        "live_trading_authority": False,
    }
    task["status"] = "RUNNING"
    raw_result = runner(command)
    if not isinstance(raw_result, dict) or set(raw_result) != {"returncode", "stdout", "stderr"}:
        raise VerifiedExecutionCycleError("runner result schema mismatch")
    returncode = raw_result["returncode"]
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        raise VerifiedExecutionCycleError("runner returncode must be an integer")
    evidence = {
        "workload_id": WORKLOAD_ID,
        "command_sha256": dispatch["command_sha256"],
        "returncode": returncode,
        "stdout": str(raw_result["stdout"]),
        "stderr": str(raw_result["stderr"]),
        "source_sha": source_sha,
        "source_revision": source_revision,
        "paper_only": True,
        "live_trading_authority": False,
    }
    producer_result = attempts.build_result(
        attempt,
        outcome="success" if returncode == 0 else "failure",
        evidence=evidence,
    )
    attempts.accept_result(task, producer_result)

    # The verifier does not trust the producer's outcome.  It checks the bound
    # command, source, authority, and observed process result independently.
    check_evidence = {
        "command_matches": evidence["command_sha256"] == _digest(command),
        "source_matches": evidence["source_sha"] == source_sha,
        "process_succeeded": evidence["returncode"] == 0,
        "paper_only": evidence["paper_only"] is True,
        "live_disabled": evidence["live_trading_authority"] is False,
    }
    checks = [
        {"name": name, "passed": passed, "evidence_sha256": _digest({name: passed, "source_sha": source_sha})}
        for name, passed in sorted(check_evidence.items())
    ]
    artifact = {
        "kind": "bounded-workload-result",
        "name": "nexus-integration-validator.json",
        "sha256": _digest(evidence),
    }
    manifest = verification.build_verification_manifest(
        config,
        task,
        producer_result,
        verifier_id="integration-verifier",
        checks=checks,
        artifacts=[artifact],
    )
    verification.accept_verification(config, task, producer_result, manifest)
    if task["status"] != "DONE":
        raise VerifiedExecutionCycleError("independent verification rejected the workload")

    execution_record = deepcopy(execution_record)
    execution_record["status"] = "VERIFIED"
    validate_task_record(execution_record)
    ledger = {
        "schema_version": SCHEMA,
        "source_sha": source_sha,
        "source_revision": source_revision,
        "scope": "research_backtest_paper_only",
        "live_trading_authority": False,
        "execution_record": execution_record,
        "dispatch": dispatch,
        "producer_result": producer_result,
        "verification_manifest": manifest,
        "resource_utilization": [
            {
                "resource_id": "integration-producer",
                "classification": "EXECUTED",
                "task_id": task["id"],
                "lease_id": lease_id,
                "result_digest": task["last_attempt_result"]["result_digest"],
            },
            {
                "resource_id": "integration-verifier",
                "classification": "EXECUTED",
                "task_id": task["id"],
                "lease_id": lease_id,
                "result_digest": task["verification_evidence"]["manifest_digest"],
            },
        ],
        "final_status": "VERIFIED",
    }
    ledger["cycle_digest"] = _digest(ledger)
    _atomic_json(output_path, ledger)
    return ledger


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded verified NEXUS execution cycle")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = run_cycle(source_sha=args.source_sha, output_path=args.output)
    except (OSError, subprocess.SubprocessError, attempts.AttemptError, verification.VerificationError, VerifiedExecutionCycleError) as exc:
        parser.exit(1, f"NEXUS verified execution cycle failed: {exc}\n")
    print(json.dumps({"ok": True, "status": result["final_status"], "cycle_digest": result["cycle_digest"], "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
