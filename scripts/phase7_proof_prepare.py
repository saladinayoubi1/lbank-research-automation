from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import agent_manager as am
import agent_transport as transport
import offline_agent_courier as courier
import phase5_mission_contract as mission_contract
from phase5_state_store import SQLiteStateStore
from scripts import agent_task_executor as executor

import phase7_e2e_proof

MISSION_PATH = Path("config/nexus-phase7-proof-mission.json")
MISSION_ID = "nexus-phase7-e2e-proof"
DEEPSEEK_TASK_ID = "P7-DEEPSEEK-ADVISORY"
RESOURCE_CLASSES = ("Laptop", "Internal Agent", "Cloud/GitHub worker", "DeepSeek/AI provider")


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


def _resource_class(worker_id: str) -> str:
    if worker_id == "windows-runner":
        return "Laptop"
    if worker_id == "deepseek-bounded":
        return "DeepSeek/AI provider"
    if worker_id in {"research-agent", "paper-agent"}:
        return "Internal Agent"
    return "Cloud/GitHub worker"


def _active_load_excluding_task(config: dict[str, Any], task_id: str | None) -> dict[str, int]:
    load: dict[str, int] = {}
    for row in config.get("tasks", []):
        if task_id and row.get("id") == task_id:
            continue
        worker_id = row.get("assigned_worker")
        if row.get("status") in am.ACTIVE and worker_id:
            load[str(worker_id)] = load.get(str(worker_id), 0) + 1
    return load


def _annotated_routing(
    config: dict[str, Any],
    task: Mapping[str, Any],
    worker_id: str,
    *,
    verifier_only: bool,
) -> dict[str, Any]:
    if not verifier_only and isinstance(task.get("routing_decision"), Mapping):
        decision = deepcopy(dict(task["routing_decision"]))
        candidates = decision.get("candidates", [])
    else:
        rows = am.rank_worker_candidates(
            dict(task),
            am.workers_from(config),
            verifier_only=verifier_only,
            active_load=_active_load_excluding_task(config, str(task.get("id") or "")),
        )
        selected = next((row for row in rows if row.get("worker_id") == worker_id and row.get("eligible")), None)
        for row in rows:
            row["selection_reason"] = (
                "highest_deterministic_score" if row.get("worker_id") == worker_id and row.get("eligible")
                else ("lower_score_than_selected" if row.get("eligible") else "ineligible")
            )
        decision = {
            "evaluated_at": am.iso(),
            "selected_worker": worker_id if selected else None,
            "selected_score": selected.get("score") if selected else None,
            "reason": "highest_deterministic_score" if selected else "selected_worker_not_eligible",
            "candidates": rows,
        }
        candidates = rows
    selected_row = next((row for row in candidates if isinstance(row, Mapping) and row.get("worker_id") == worker_id), {})
    rejected = [
        {
            "worker_id": row.get("worker_id"),
            "eligible": bool(row.get("eligible")),
            "score": row.get("score"),
            "selection_reason": row.get("selection_reason"),
            "rejection_reasons": list(row.get("rejection_reasons") or []),
        }
        for row in candidates
        if isinstance(row, Mapping) and row.get("worker_id") != worker_id
    ]
    return {
        "evaluated_at": decision.get("evaluated_at"),
        "selected_worker": decision.get("selected_worker"),
        "reason": decision.get("reason"),
        "selected_score": decision.get("selected_score"),
        "selected_observed": deepcopy(selected_row.get("observed")) if isinstance(selected_row, Mapping) else None,
        "selected_components": deepcopy(selected_row.get("components")) if isinstance(selected_row, Mapping) else None,
        "rejected_alternatives": rejected,
    }


def _lease_fencing(task: Mapping[str, Any], envelope: Mapping[str, Any]) -> dict[str, Any]:
    identity = {
        "attempt": int(task.get("attempt") or 0),
        "lease_id": envelope.get("lease_id"),
        "dispatch_id": envelope.get("dispatch_id"),
    }
    return {**identity, "fencing_identity_sha256": _digest(identity)}


def _ledger_row(
    *,
    config: dict[str, Any],
    task: Mapping[str, Any],
    worker_id: str,
    role: str,
    envelope: Mapping[str, Any],
    routing: Mapping[str, Any],
    classification: str,
    outcome: str,
    evidence: Mapping[str, Any] | None,
    latency_ms: float | None,
    result_at: str | None,
    verifier_id: str | None = None,
    verifier_result: str | None = None,
    availability_reason: str | None = None,
) -> dict[str, Any]:
    if classification not in {"EXECUTED", "UNAVAILABLE"}:
        raise ValueError("resource ledger classification must be EXECUTED or UNAVAILABLE")
    observed = routing.get("selected_observed") if isinstance(routing.get("selected_observed"), Mapping) else {}
    evidence_dict = dict(evidence or {})
    return {
        "classification": classification,
        "resource_class": _resource_class(worker_id),
        "task_id": task.get("id"),
        "role": role,
        "worker_id": worker_id,
        "resource": (task.get("dispatch_transport") or envelope.get("transport") or "unknown"),
        "routing": dict(routing),
        "lease_fencing": _lease_fencing(task, envelope),
        "timestamps": {
            "leased_at": task.get("leased_at"),
            "dispatch_at": task.get("dispatched_at"),
            "heartbeat_at": task.get("heartbeat_at"),
            "result_at": result_at,
        },
        "result": {
            "outcome": outcome,
            "evidence_sha256": _digest(evidence_dict) if evidence is not None else None,
            "failure_class": evidence_dict.get("failure_class"),
        },
        "verifier": {"worker_id": verifier_id, "result": verifier_result},
        "latency_ms": round(float(latency_ms), 3) if latency_ms is not None else None,
        "retry_failure": {
            "transient_retries": int(task.get("transient_retries") or 0),
            "observed_failure_rate": observed.get("failure_rate"),
        },
        "budget_cost": {
            "routing_cost_units": observed.get("cost_units"),
            "provider_cost_usd": evidence_dict.get("cost_usd"),
        },
        "availability_reason": availability_reason,
    }


def resource_classification(ledger: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for resource_class in RESOURCE_CLASSES:
        rows = [row for row in ledger if row.get("resource_class") == resource_class]
        executed = [row for row in rows if row.get("classification") == "EXECUTED" and row.get("result", {}).get("outcome") == "success"]
        unavailable = [row for row in rows if row.get("classification") == "UNAVAILABLE"]
        if executed:
            status = "EXECUTED"
            reason = None
        elif unavailable:
            status = "UNAVAILABLE"
            reason = next((row.get("availability_reason") for row in unavailable if row.get("availability_reason")), "unavailable")
        else:
            status = "UNAVAILABLE"
            reason = "no_resource_ledger_entry"
        summary[resource_class] = {
            "classification": status,
            "reason": reason,
            "task_ids": sorted({str(row.get("task_id")) for row in rows if row.get("task_id")}),
            "worker_ids": sorted({str(row.get("worker_id")) for row in rows if row.get("worker_id")}),
            "executed_rows": len(executed),
            "unavailable_rows": len(unavailable),
        }
    return summary


def _execute_and_verify(config: dict[str, Any], task_id: str, ledger: list[dict[str, Any]]) -> None:
    task = am.task_index(config)[task_id]
    if task.get("status") != "LEASED":
        raise RuntimeError(f"{task_id} is not leased for producer execution")

    producer = str(task.get("assigned_worker"))
    producer_snapshot = deepcopy(task)
    producer_routing = _annotated_routing(config, producer_snapshot, producer, verifier_only=False)
    envelope = _direct_dispatch_identity(task)
    producer_snapshot.update({
        "dispatch_transport": task.get("dispatch_transport"),
        "dispatched_at": task.get("dispatched_at"),
        "correlation_id": task.get("correlation_id"),
        "dispatch_id": task.get("dispatch_id"),
    })
    if envelope["transport"] != "github-cloud":
        raise RuntimeError(f"{task_id} producer is not routed to GitHub cloud")
    started = time.perf_counter()
    result = executor.execute(envelope, "github-cloud")
    elapsed = (time.perf_counter() - started) * 1000.0
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    transport.ingest_result(config, task, result)
    producer_result_at = task.get("result_received_at")
    verifier_id = task.get("verifier") if result["outcome"] == "success" else None
    ledger.append(
        _ledger_row(
            config=config,
            task=producer_snapshot,
            worker_id=producer,
            role="producer",
            envelope=envelope,
            routing=producer_routing,
            classification="EXECUTED",
            outcome=result["outcome"],
            evidence=evidence,
            latency_ms=elapsed,
            result_at=producer_result_at,
            verifier_id=verifier_id,
            verifier_result="assigned" if verifier_id else None,
        )
    )
    if result["outcome"] != "success":
        return
    if task.get("status") != "VERIFYING":
        raise RuntimeError(f"{task_id} did not enter independent verification")
    if task.get("assigned_worker") == producer:
        raise RuntimeError(f"{task_id} producer attempted self-verification")

    verifier = str(task.get("assigned_worker"))
    verifier_snapshot = deepcopy(task)
    verifier_routing = _annotated_routing(config, verifier_snapshot, verifier, verifier_only=True)
    verifier_envelope = _direct_dispatch_identity(task)
    verifier_snapshot.update({
        "dispatch_transport": task.get("dispatch_transport"),
        "dispatched_at": task.get("dispatched_at"),
        "correlation_id": task.get("correlation_id"),
        "dispatch_id": task.get("dispatch_id"),
    })
    if verifier_envelope["transport"] != "github-cloud":
        raise RuntimeError(f"{task_id} verifier is not routed to GitHub cloud")
    started = time.perf_counter()
    verification = executor.execute(verifier_envelope, "github-cloud")
    elapsed = (time.perf_counter() - started) * 1000.0
    verification_evidence = verification.get("evidence") if isinstance(verification.get("evidence"), dict) else {}
    transport.ingest_result(config, task, verification)
    ledger.append(
        _ledger_row(
            config=config,
            task=verifier_snapshot,
            worker_id=verifier,
            role="verifier",
            envelope=verifier_envelope,
            routing=verifier_routing,
            classification="EXECUTED",
            outcome=verification["outcome"],
            evidence=verification_evidence,
            latency_ms=elapsed,
            result_at=task.get("result_received_at"),
            verifier_id=verifier,
            verifier_result="success" if verification["outcome"] == "success" else "failure",
        )
    )


def _deepseek_virtual_task(config: dict[str, Any], source_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    task = {
        "id": DEEPSEEK_TASK_ID,
        "title": "Bounded advisory critique of the Phase 7 Proof Mission evidence contract",
        "phase": 7,
        "gate": 0,
        "status": "LEASED",
        "priority": 30,
        "dependencies": [],
        "required_capabilities": ["code_review"],
        "preferred_resources": ["deepseek"],
        "preferred_trust_domains": ["deepseek-external"],
        "authority": 1,
        "acceptance": ["bounded advisory evidence returned", "no credential or authority expansion"],
        "assigned_worker": "deepseek-bounded",
        "producer": "deepseek-bounded",
        "lease_id": _digest({"kind": "phase7-deepseek-lease", "source_sha": source_sha})[:32],
        "leased_at": am.iso(),
        "heartbeat_at": am.iso(),
        "attempt": 1,
    }
    routing = _annotated_routing(config, task, "deepseek-bounded", verifier_only=False)
    task["routing_decision"] = {
        "evaluated_at": routing["evaluated_at"],
        "selected_worker": routing["selected_worker"],
        "selected_score": routing["selected_score"],
        "reason": routing["reason"],
        "candidates": am.rank_worker_candidates(task, am.workers_from(config), active_load=_active_load_excluding_task(config, DEEPSEEK_TASK_ID)),
    }
    envelope = _direct_dispatch_identity(task)
    return task, envelope


def _run_deepseek_advisory(config: dict[str, Any], source_sha: str, ledger: list[dict[str, Any]]) -> dict[str, Any]:
    gate = os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1"
    key_present = bool(os.environ.get("DEEPSEEK_API_KEY"))
    task, envelope = _deepseek_virtual_task(config, source_sha)
    routing = _annotated_routing(config, task, "deepseek-bounded", verifier_only=False)
    if not gate or not key_present:
        reason = "missing_provider_configuration" if not key_present else "provider_budget_gate_closed"
        ledger.append(
            _ledger_row(
                config=config,
                task=task,
                worker_id="deepseek-bounded",
                role="advisory",
                envelope=envelope,
                routing=routing,
                classification="UNAVAILABLE",
                outcome="not_executed",
                evidence=None,
                latency_ms=None,
                result_at=None,
                availability_reason=reason,
            )
        )
        return {"status": "UNAVAILABLE", "reason": reason, "task_id": DEEPSEEK_TASK_ID}

    started = time.perf_counter()
    result = executor.execute(envelope, "deepseek")
    elapsed = (time.perf_counter() - started) * 1000.0
    evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else {}
    success = result.get("outcome") == "success"
    ledger.append(
        _ledger_row(
            config=config,
            task=task,
            worker_id="deepseek-bounded",
            role="advisory",
            envelope=envelope,
            routing=routing,
            classification="EXECUTED" if success else "UNAVAILABLE",
            outcome=str(result.get("outcome")),
            evidence=evidence,
            latency_ms=elapsed,
            result_at=am.iso(),
            availability_reason=None if success else str(evidence.get("failure_class") or "provider_result_unavailable"),
        )
    )
    if not success:
        return {
            "status": "UNAVAILABLE",
            "reason": str(evidence.get("failure_class") or "provider_result_unavailable"),
            "task_id": DEEPSEEK_TASK_ID,
            "evidence_sha256": _digest(evidence),
        }
    return {
        "status": "EXECUTED",
        "task_id": DEEPSEEK_TASK_ID,
        "model": evidence.get("model"),
        "cost_usd": evidence.get("cost_usd"),
        "evidence_sha256": _digest(evidence),
    }


def prepare(source_sha: str, output_dir: Path, *, mission_path: Path = MISSION_PATH) -> dict[str, Any]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    am.EVENT_PATH = output_dir / "manager-events.jsonl"
    runtime_path = output_dir / "agent-manager-runtime.json"
    manager_summary_path = output_dir / "manager-state.json"
    state_db = output_dir / "phase7-supervisor-state.sqlite3"
    store = SQLiteStateStore(state_db)
    config = load_runtime_template(mission_path)
    deepseek_configured = (
        os.environ.get("NEXUS_DEEPSEEK_PAID_ROUTING_ALLOWED") == "1"
        and bool(os.environ.get("DEEPSEEK_API_KEY"))
    )
    if "deepseek-bounded" in config.get("resource_metrics", {}):
        config["resource_metrics"]["deepseek-bounded"]["available"] = deepseek_configured

    state = _persist(store, config, None)
    summary = am.cycle(config)
    state = _persist(store, config, state.generation)
    am.atomic_json(runtime_path, config)
    am.atomic_json(manager_summary_path, summary)

    resource_ledger: list[dict[str, Any]] = []
    laptop = am.task_index(config)["P7-LAPTOP-CANONICAL"]
    laptop_snapshot = deepcopy(laptop)
    laptop_routing = _annotated_routing(config, laptop_snapshot, str(laptop.get("assigned_worker")), verifier_only=False)
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
        laptop_snapshot.update({
            "dispatch_transport": "offline-courier",
            "dispatched_at": laptop.get("dispatched_at"),
            "heartbeat_at": laptop.get("heartbeat_at"),
        })
        envelope = bundle["payload"]
        resource_ledger.append(
            _ledger_row(
                config=config,
                task=laptop_snapshot,
                worker_id="windows-runner",
                role="producer",
                envelope=envelope,
                routing=laptop_routing,
                classification="UNAVAILABLE",
                outcome="WAITING_EXTERNAL",
                evidence={"payload_sha256": bundle["payload_sha256"]},
                latency_ms=None,
                result_at=None,
                availability_reason="awaiting_real_offline_laptop_execution",
            )
        )
        state = _persist(store, config, state.generation)
    else:
        reason = f"{courier.KEY_ENV} is absent or shorter than {courier.MIN_KEY_BYTES} bytes"
        courier_status = {
            "status": "KEY_UNAVAILABLE",
            "task_id": "P7-LAPTOP-CANONICAL",
            "worker_id": laptop.get("assigned_worker"),
            "resource": "windows-local",
            "offline_execution_required": True,
            "reason": reason,
        }
        pseudo_envelope = {
            "lease_id": laptop.get("lease_id"),
            "dispatch_id": transport.dispatch_id_for(laptop),
            "transport": "windows",
        }
        resource_ledger.append(
            _ledger_row(
                config=config,
                task=laptop_snapshot,
                worker_id="windows-runner",
                role="producer",
                envelope=pseudo_envelope,
                routing=laptop_routing,
                classification="UNAVAILABLE",
                outcome="not_executed",
                evidence=None,
                latency_ms=None,
                result_at=None,
                availability_reason="missing_courier_key",
            )
        )

    _execute_and_verify(config, "P7-CLOUD-VERIFY", resource_ledger)
    state = _persist(store, config, state.generation)

    am.cycle(config)
    research_task = am.task_index(config)["P7-RESEARCH-STRATEGY"]
    _execute_and_verify(config, "P7-RESEARCH-STRATEGY", resource_ledger)
    state = _persist(store, config, state.generation)

    am.cycle(config)
    _execute_and_verify(config, "P7-PAPER-PERFORMANCE", resource_ledger)
    state = _persist(store, config, state.generation)

    deepseek_status = _run_deepseek_advisory(config, source_sha, resource_ledger)

    e2e = phase7_e2e_proof.build_proof(source_sha)
    phase7_e2e_proof.validate_proof(e2e, expected_source_sha=source_sha)
    _write(output_dir / "phase7-e2e-proof.json", e2e)

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
        "resource_classification": resource_classification(resource_ledger),
        "courier": courier_status,
        "deepseek": deepseek_status,
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
