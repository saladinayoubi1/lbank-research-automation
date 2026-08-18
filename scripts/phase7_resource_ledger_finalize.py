from __future__ import annotations

import argparse
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import agent_manager as am
from scripts import phase7_proof_complete as secure_completion
from scripts import phase7_proof_prepare as prepare

TASK_ID = secure_completion.TASK_ID
EXPECTED_PRODUCER = secure_completion.EXPECTED_PRODUCER
EXPECTED_VERIFIER = secure_completion.EXPECTED_VERIFIER


class Phase7LedgerFinalizeError(RuntimeError):
    pass


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Phase7LedgerFinalizeError(f"cannot read {path.name}") from exc
    if not isinstance(value, dict):
        raise Phase7LedgerFinalizeError(f"{path.name} root must be an object")
    return value


def _seconds_between(start: Any, end: Any) -> float | None:
    if not isinstance(start, str) or not isinstance(end, str):
        return None
    try:
        a = datetime.fromisoformat(start.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return None
    value = (b - a).total_seconds() * 1000.0
    return round(max(0.0, value), 3)


def _existing_laptop_producer(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    matches = [
        row for row in ledger
        if row.get("task_id") == TASK_ID
        and row.get("worker_id") == EXPECTED_PRODUCER
        and row.get("role") == "producer"
    ]
    if len(matches) != 1:
        raise Phase7LedgerFinalizeError("prepared ledger must contain exactly one laptop producer row")
    return deepcopy(matches[0])


def _legacy_completion_row(ledger: list[dict[str, Any]], role: str) -> dict[str, Any] | None:
    for row in reversed(ledger):
        if row.get("task_id") == TASK_ID and row.get("role") == role:
            return deepcopy(row)
    return None


def _assert_prepared_schema(row: Mapping[str, Any]) -> None:
    if row.get("classification") != "UNAVAILABLE" or row.get("resource_class") != "Laptop":
        raise Phase7LedgerFinalizeError("prepared laptop row is not an unexecuted Laptop resource")
    if row.get("availability_reason") != "awaiting_real_offline_laptop_execution":
        raise Phase7LedgerFinalizeError("prepared laptop row is not waiting on real offline execution")
    if not isinstance(row.get("routing"), Mapping) or not isinstance(row.get("lease_fencing"), Mapping):
        raise Phase7LedgerFinalizeError("prepared laptop routing/fencing evidence is missing")


def _normalize(
    prepared_run: Mapping[str, Any],
    completed_run: Mapping[str, Any],
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    if completed_run.get("hardware_proof_complete") is not True:
        raise Phase7LedgerFinalizeError("hardware proof is not complete")
    if completed_run.get("core_cloud_chain_complete") is not True:
        raise Phase7LedgerFinalizeError("cloud proof chain is not complete")
    task = am.task_index(dict(runtime)).get(TASK_ID)
    if not isinstance(task, Mapping) or task.get("status") != "DONE":
        raise Phase7LedgerFinalizeError("verified laptop task is not DONE")
    producer_evidence = task.get("result_evidence")
    verification_evidence = task.get("verification_evidence")
    if not isinstance(producer_evidence, Mapping) or not isinstance(verification_evidence, Mapping):
        raise Phase7LedgerFinalizeError("laptop producer/verifier evidence is missing")

    prepared_ledger = [dict(row) for row in prepared_run.get("resource_ledger", []) if isinstance(row, Mapping)]
    completed_ledger = [dict(row) for row in completed_run.get("resource_ledger", []) if isinstance(row, Mapping)]
    laptop = _existing_laptop_producer(prepared_ledger)
    _assert_prepared_schema(laptop)

    legacy_producer = _legacy_completion_row(completed_ledger, "producer_result")
    legacy_verifier = _legacy_completion_row(completed_ledger, "verifier")
    if legacy_producer is None or legacy_verifier is None:
        raise Phase7LedgerFinalizeError("secure completion ledger rows are missing")

    laptop["classification"] = "EXECUTED"
    laptop["availability_reason"] = None
    laptop["result"] = {
        "outcome": "success",
        "evidence_sha256": prepare._digest(dict(producer_evidence)),
        "failure_class": producer_evidence.get("failure_class"),
    }
    laptop["verifier"] = {"worker_id": EXPECTED_VERIFIER, "result": "success"}
    laptop["timestamps"]["result_at"] = task.get("result_received_at")
    laptop["latency_ms"] = _seconds_between(laptop["timestamps"].get("dispatch_at"), task.get("result_received_at"))
    laptop["result_bundle_sha256"] = completed_run.get("courier", {}).get("result_bundle_sha256")

    verifier_lease = legacy_verifier.get("lease_id")
    verifier_dispatch = legacy_verifier.get("dispatch_id")
    verifier_transport = legacy_verifier.get("transport") or "github-cloud"
    verifier_task = dict(task)
    verifier_task.update(
        {
            "status": "VERIFYING",
            "assigned_worker": EXPECTED_VERIFIER,
            "producer": EXPECTED_PRODUCER,
            "verifier": EXPECTED_VERIFIER,
            "lease_id": verifier_lease,
            "dispatch_id": verifier_dispatch,
            "dispatch_transport": verifier_transport,
            "dispatched_at": task.get("dispatched_at"),
        }
    )
    routing = prepare._annotated_routing(dict(runtime), verifier_task, EXPECTED_VERIFIER, verifier_only=True)
    envelope = {
        "lease_id": verifier_lease,
        "dispatch_id": verifier_dispatch,
        "transport": verifier_transport,
    }
    verifier_row = prepare._ledger_row(
        config=dict(runtime),
        task=verifier_task,
        worker_id=EXPECTED_VERIFIER,
        role="verifier",
        envelope=envelope,
        routing=routing,
        classification="EXECUTED",
        outcome="success",
        evidence=dict(verification_evidence),
        latency_ms=_seconds_between(task.get("dispatched_at"), task.get("verified_at")),
        result_at=task.get("verified_at"),
        verifier_id=EXPECTED_VERIFIER,
        verifier_result="success",
    )

    other_rows = [
        row for row in completed_ledger
        if row.get("task_id") != TASK_ID
    ]
    ledger = [*other_rows, laptop, verifier_row]
    result = dict(completed_run)
    result["resource_ledger"] = ledger
    result["resource_classification"] = prepare.resource_classification(ledger)
    if result["resource_classification"]["Laptop"]["classification"] != "EXECUTED":
        raise Phase7LedgerFinalizeError("Laptop resource did not classify as EXECUTED")
    result.pop("run_digest", None)
    result["run_digest"] = prepare._digest(result)
    return result


def finalize(artifact_dir: Path, returned_result: Path) -> dict[str, Any]:
    artifact_dir = Path(artifact_dir)
    run_path = artifact_dir / "phase7-proof-mission-run.json"
    runtime_path = artifact_dir / "agent-manager-runtime.json"
    prepared = _read(run_path)

    if prepared.get("hardware_proof_complete") is True:
        completed = prepared
        # A prior secure completion can be normalized without replaying Courier.
        prepared_snapshot_path = artifact_dir / "phase7-proof-prepared-run.json"
        if not prepared_snapshot_path.is_file():
            raise Phase7LedgerFinalizeError("prepared run snapshot required for idempotent ledger normalization")
        prepared = _read(prepared_snapshot_path)
    else:
        snapshot = artifact_dir / "phase7-proof-prepared-run.json"
        if not snapshot.exists():
            secure_completion._write_json(snapshot, prepared)
        completed = secure_completion.complete(artifact_dir, Path(returned_result))

    runtime = _read(runtime_path)
    normalized = _normalize(prepared, completed, runtime)
    secure_completion._write_json(run_path, normalized)
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Securely complete and normalize the Phase 7 laptop resource ledger")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--returned-result", required=True)
    args = parser.parse_args()
    result = finalize(Path(args.artifact_dir), Path(args.returned_result))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
