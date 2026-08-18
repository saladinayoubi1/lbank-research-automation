from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import agent_manager as am
import agent_transport as transport
import offline_agent_courier as courier
import phase5_mission_contract as mission_contract
from phase5_state_store import SQLiteStateStore
from scripts import agent_task_executor as executor

import phase7_e2e_proof

MISSION_PATH = Path("config/nexus-phase7-proof-mission.json")
MISSION_ID = "nexus-phase7-e2e-proof"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n")
    os.replace(tmp, path)


def load_runtime_template(path: Path = MISSION_PATH) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    mission = mission_contract.validate_and_materialize(raw)
    runtime = mission_contract.to_agent_manager_config(raw)
    runtime["resource_metrics"] = deepcopy(mission.get("resource_metrics", {}))
    am.validate_config(runtime)
    if runtime.get("mission_id") != MISSION_ID or runtime.get("phase") != 7:
        raise ValueError("unexpected Phase 7 Proof Mission identity")
    return runtime


def _persist(store: SQLiteStateStore, config: dict[str, Any], generation: int | None):
    return store.compare_and_swap(MISSION_ID, generation, config)


def _direct_dispatch_identity(task: dict[str, Any]) -> dict[str, Any]:
    envelope = transport.envelope_for(task)
    task["status"] = "RUNNING" if task.get("status") == "LEASED" else task.get("status")
    task["correlation_id"] = envelope["correlation_id"]
    task["dispatch_id"] = envelope["dispatch_id"]
    task["dispatch_transport"] = envelope["transport"]
    task["dispatch_mode"] = "github-hosted-direct-proof"
    task["dispatched_at"] = am.iso()
    return envelope


def _execute_and_verify(config: dict[str, Any], task_id: str, ledger: list[dict[str, Any]]) -> None:
    task = am.task_index(config)[task_id]
    if task.get("status") != "LEASED":
        raise RuntimeError(f"{task_id} is not leased for producer execution")

    producer = task.get("assigned_worker")
    producer_lease = task.get("lease_id")
    envelope = _direct_dispatch_identity(task)
    if envelope["transport"] != "github-cloud":
        raise RuntimeError(f"{task_id} producer is not routed to GitHub cloud")
    result = executor.execute(envelope, "github-cloud")
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    ledger.append(
        {
            "task_id": task_id,
            "role": "producer",
            "worker_id": producer,
            "resource": "github-cloud",
            "lease_id": producer_lease,
            "correlation_id": envelope["correlation_id"],
            "dispatch_id": envelope["dispatch_id"],
            "transport": envelope["transport"],
            "outcome": result["outcome"],
            "evidence_sha256": _digest(evidence),
        }
    )
    transport.ingest_result(config, task, result)
    if result["outcome"] != "success":
        return
    if task.get("status") != "VERIFYING":
        raise RuntimeError(f"{task_id} did not enter independent verification")
    if task.get("assigned_worker") == producer:
        raise RuntimeError(f"{task_id} producer attempted self-verification")

    verifier = task.get("assigned_worker")
    verifier_lease = task.get("lease_id")
    verifier_envelope = _direct_dispatch_identity(task)
    if verifier_envelope["transport"] != "github-cloud":
        raise RuntimeError(f"{task_id} verifier is not routed to GitHub cloud")
    verification = executor.execute(verifier_envelope, "github-cloud")
    verification_evidence = verification.get("evidence") if isinstance(verification.get("evidence"), dict) else {}
    ledger.append(
        {
            "task_id": task_id,
            "role": "verifier",
            "worker_id": verifier,
            "resource": "github-cloud",
            "lease_id": verifier_lease,
            "correlation_id": verifier_envelope["correlation_id"],
            "dispatch_id": verifier_envelope["dispatch_id"],
            "transport": verifier_envelope["transport"],
            "outcome": verification["outcome"],
            "evidence_sha256": _digest(verification_evidence),
        }
    )
    transport.ingest_result(config, task, verification)


def _deepseek_status() -> dict[str, Any]:
    gate = os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1"
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY"))
    if gate and key_present:
        return {"status": "NOT_SELECTED", "reason": "provider available but not required by core proof DAG"}
    reason = "budget_gate_closed" if not gate else "api_key_unavailable"
    return {"status": "UNAVAILABLE", "reason": reason}


def prepare(source_sha: str, output_dir: Path, *, mission_path: Path = MISSION_PATH) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    am.EVENT_PATH = output_dir / "manager-events.jsonl"
    runtime_path = output_dir / "agent-manager-runtime.json"
    manager_summary_path = output_dir / "manager-state.json"
    state_db = output_dir / "phase7-supervisor-state.sqlite3"
    store = SQLiteStateStore(state_db)
    config = load_runtime_template(mission_path)

    state = _persist(store, config, None)
    summary = am.cycle(config)
    state = _persist(store, config, state.generation)
    am.atomic_json(runtime_path, config)
    am.atomic_json(manager_summary_path, summary)

    resource_ledger: list[dict[str, Any]] = []
    laptop = am.task_index(config)["P7-LAPTOP-CANONICAL"]
    courier_status: dict[str, Any]
    key_value = os.environ.get(courier.KEY_ENV)
    if key_value and len(key_value.encode("utf-8")) >= courier.MIN_KEY_BYTES:
        dispatch_path = output_dir / "courier" / "phase7-laptop-dispatch.json"
        bundle = courier.export_task(
            config,
            "P7-LAPTOP-CANONICAL",
            dispatch_path,
            runtime_path=runtime_path,
            summary_path=manager_summary_path,
        )
        courier_status = {
            "status": "EXPORTED",
            "task_id": "P7-LAPTOP-CANONICAL",
            "worker_id": laptop.get("assigned_worker"),
            "resource": "windows-local",
            "lease_id": laptop.get("lease_id"),
            "correlation_id": laptop.get("correlation_id"),
            "dispatch_id": laptop.get("dispatch_id"),
            "payload_sha256": bundle["payload_sha256"],
            "bundle": str(dispatch_path.relative_to(output_dir)),
            "offline_execution_required": True,
        }
        resource_ledger.append({**courier_status, "role": "producer", "transport": "offline-courier", "outcome": "WAITING_EXTERNAL"})
        state = _persist(store, config, state.generation)
    else:
        courier_status = {
            "status": "KEY_UNAVAILABLE",
            "task_id": "P7-LAPTOP-CANONICAL",
            "worker_id": laptop.get("assigned_worker"),
            "resource": "windows-local",
            "offline_execution_required": True,
            "reason": f"{courier.KEY_ENV} is absent or shorter than {courier.MIN_KEY_BYTES} bytes",
        }

    _execute_and_verify(config, "P7-CLOUD-VERIFY", resource_ledger)
    state = _persist(store, config, state.generation)

    am.cycle(config)
    research_task = am.task_index(config)["P7-RESEARCH-STRATEGY"]
    _execute_and_verify(config, "P7-RESEARCH-STRATEGY", resource_ledger)
    state = _persist(store, config, state.generation)

    am.cycle(config)
    _execute_and_verify(config, "P7-PAPER-PERFORMANCE", resource_ledger)
    state = _persist(store, config, state.generation)

    e2e = phase7_e2e_proof.build_proof(source_sha)
    phase7_e2e_proof.validate_proof(e2e, expected_source_sha=source_sha)
    e2e_path = output_dir / "phase7-e2e-proof.json"
    _write(e2e_path, e2e)

    final_summary = am.summarize(config)
    am.atomic_json(runtime_path, config)
    am.atomic_json(manager_summary_path, final_summary)
    zero_idle = research_task.get("zero_idle_evidence")
    proof = {
        "schema_version": "nexus.phase7-proof-mission-run.v1",
        "mission_id": MISSION_ID,
        "source_sha": source_sha.lower(),
        "paper_only": True,
        "live_trading_authority": False,
        "state_generation": state.generation,
        "state_sha256": state.payload_sha256,
        "manager_summary": final_summary,
        "resource_ledger": resource_ledger,
        "courier": courier_status,
        "deepseek": _deepseek_status(),
        "zero_idle_evidence": zero_idle,
        "e2e_proof_digest": e2e["proof_digest"],
        "hardware_proof_complete": am.task_index(config)["P7-LAPTOP-CANONICAL"].get("status") == "DONE",
        "core_cloud_chain_complete": all(
            am.task_index(config)[task_id].get("status") == "DONE"
            for task_id in ("P7-CLOUD-VERIFY", "P7-RESEARCH-STRATEGY", "P7-PAPER-PERFORMANCE")
        ),
    }
    proof["run_digest"] = _digest(proof)
    _write(output_dir / "phase7-proof-mission-run.json", proof)
    return proof


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare and execute the cloud side of the NEXUS Phase 7 Proof Mission")
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output-dir", default="build/phase7-proof")
    parser.add_argument("--mission", default=str(MISSION_PATH))
    args = parser.parse_args()
    result = prepare(args.source_sha, Path(args.output_dir), mission_path=Path(args.mission))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
