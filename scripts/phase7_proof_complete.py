from __future__ import annotations

import argparse
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

import agent_manager as am
import agent_transport as transport
import offline_agent_courier as courier
import phase7_e2e_proof
from phase5_state_store import SQLiteStateStore
from scripts import agent_task_executor as executor
from scripts.phase7_proof_prepare import MISSION_ID

RUN_SCHEMA = "nexus.phase7-proof-mission-run.v1"
VERIFY_SCHEMA = "nexus.phase7-laptop-verification.v1"
TASK_ID = "P7-LAPTOP-CANONICAL"
EXPECTED_PRODUCER = "windows-runner"
EXPECTED_VERIFIER = "qa-verifier-agent"
EXPECTED_LAPTOP_SUITE = [
    "tests/test_phase5_data_binding.py",
    "tests/test_canonical_backtest_boundary.py",
    "tests/test_product_offline_runtime.py",
]
CLOUD_VERIFIER_SUITE = [
    "tests/test_offline_agent_courier.py",
    "tests/test_phase7_courier_restore.py",
    "tests/test_canonical_backtest_boundary.py",
    "tests/test_product_offline_runtime.py",
]
MAX_JSON_BYTES = 2_000_000


class Phase7CompletionError(RuntimeError):
    pass


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise Phase7CompletionError("completion payload is not canonical JSON") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase7CompletionError(f"{label} is unavailable") from exc
    if not raw or len(raw) > MAX_JSON_BYTES:
        raise Phase7CompletionError(f"{label} size is outside bounds")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase7CompletionError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise Phase7CompletionError(f"{label} root must be an object")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        dict(payload),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8") + b"\n"
    if len(raw) > MAX_JSON_BYTES:
        raise Phase7CompletionError("completed proof exceeds bounded size")
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(raw)
    os.replace(tmp, path)


def _require_cloud_verifier_environment() -> None:
    if os.environ.get("NEXUS_PHASE7_TEST_VERIFIER") == "1":
        return
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise Phase7CompletionError("independent laptop verification must run on GitHub Actions")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo != "saladinayoubi1/lbank-research-automation":
        raise Phase7CompletionError("independent verifier repository identity mismatch")


def _worker(config: Mapping[str, Any], worker_id: str) -> dict[str, Any]:
    for row in config.get("workers", []):
        if isinstance(row, Mapping) and row.get("id") == worker_id:
            return dict(row)
    raise Phase7CompletionError(f"worker {worker_id} missing from proof runtime")


def _validate_prepared_artifact(
    artifact_dir: Path,
    run: Mapping[str, Any],
    config: Mapping[str, Any],
    state_store: SQLiteStateStore,
) -> tuple[str, Any]:
    if run.get("schema_version") != RUN_SCHEMA or run.get("mission_id") != MISSION_ID:
        raise Phase7CompletionError("prepared Proof Mission run identity mismatch")
    if run.get("paper_only") is not True or run.get("live_trading_authority") is not False:
        raise Phase7CompletionError("prepared Proof Mission widened authority")
    if run.get("core_cloud_chain_complete") is not True:
        raise Phase7CompletionError("cloud Proof Mission chain is incomplete")
    if run.get("hardware_proof_complete") is not False:
        raise Phase7CompletionError("laptop hardware proof was already completed")
    courier_status = run.get("courier")
    if not isinstance(courier_status, Mapping) or courier_status.get("status") != "EXPORTED":
        raise Phase7CompletionError("prepared artifact does not contain an exported Courier dispatch")
    if courier_status.get("task_id") != TASK_ID or courier_status.get("worker_id") != EXPECTED_PRODUCER:
        raise Phase7CompletionError("Courier dispatch identity is not the Phase 7 laptop task")

    source_sha = run.get("source_sha")
    if not isinstance(source_sha, str) or len(source_sha) != 40:
        raise Phase7CompletionError("prepared source SHA is invalid")
    e2e = _read_json(artifact_dir / "phase7-e2e-proof.json", "Phase 7 E2E proof")
    phase7_e2e_proof.validate_proof(e2e, expected_source_sha=source_sha)
    if e2e.get("proof_digest") != run.get("e2e_proof_digest"):
        raise Phase7CompletionError("prepared E2E proof digest mismatch")

    current = state_store.load_current(MISSION_ID)
    if current is None:
        raise Phase7CompletionError("durable Proof Mission state is missing")
    if current.generation != run.get("state_generation") or current.payload_sha256 != run.get("state_sha256"):
        raise Phase7CompletionError("durable Proof Mission state does not match prepared run")
    if _digest(config) != current.payload_sha256:
        raise Phase7CompletionError("runtime JSON does not match durable Proof Mission state")
    return source_sha.lower(), current


def _validate_returned_laptop_evidence(task: Mapping[str, Any]) -> dict[str, Any]:
    if task.get("producer") != EXPECTED_PRODUCER:
        raise Phase7CompletionError("laptop result producer identity mismatch")
    evidence = task.get("result_evidence")
    if not isinstance(evidence, Mapping):
        raise Phase7CompletionError("laptop result evidence is missing")
    if evidence.get("executor") != "bounded-pytest" or evidence.get("workload_id") != TASK_ID:
        raise Phase7CompletionError("laptop result is not the bounded Phase 7 workload")
    if evidence.get("purpose") != "canonical-data-and-offline-backtest-proof":
        raise Phase7CompletionError("laptop result purpose mismatch")
    if evidence.get("suite") != EXPECTED_LAPTOP_SUITE:
        raise Phase7CompletionError("laptop result suite mismatch")
    if evidence.get("offline_capable") is not True or evidence.get("network_required") is not False:
        raise Phase7CompletionError("laptop result does not prove the offline workload boundary")
    if evidence.get("transport") != "windows":
        raise Phase7CompletionError("laptop result transport is not Windows")
    tests = evidence.get("tests")
    if not isinstance(tests, Mapping) or tests.get("ok") is not True or tests.get("returncode") != 0:
        raise Phase7CompletionError("laptop bounded workload did not pass")
    if evidence.get("failure_class") is not None:
        raise Phase7CompletionError("laptop result carries a failure classification")
    return dict(evidence)


def _validate_zero_idle(run: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    research = am.task_index(dict(config)).get("P7-RESEARCH-STRATEGY")
    evidence = research.get("zero_idle_evidence") if isinstance(research, Mapping) else None
    if not isinstance(evidence, Mapping):
        raise Phase7CompletionError("zero-idle overlap evidence is missing")
    if evidence.get("rule") != "dispatch_independent_ready_work_while_other_resource_waits":
        raise Phase7CompletionError("zero-idle overlap rule mismatch")
    waits = evidence.get("overlapped_external_waits")
    if not isinstance(waits, list) or not any(isinstance(row, Mapping) and row.get("task_id") == TASK_ID for row in waits):
        raise Phase7CompletionError("zero-idle evidence is not bound to the laptop Courier wait")
    prepared = run.get("zero_idle_evidence")
    if not isinstance(prepared, Mapping) or _digest(prepared) != _digest(evidence):
        raise Phase7CompletionError("zero-idle evidence changed from the prepared proof")
    return dict(evidence)


def _run_independent_verifier() -> dict[str, Any]:
    result = executor.run(["python", "-m", "pytest", "-q", *CLOUD_VERIFIER_SUITE], timeout=900)
    if result.get("ok") is not True or result.get("returncode") != 0:
        raise Phase7CompletionError("independent cloud verifier regression suite failed")
    return result


def complete(artifact_dir: Path, returned_result: Path) -> dict[str, Any]:
    _require_cloud_verifier_environment()
    artifact_dir = Path(artifact_dir)
    runtime_path = artifact_dir / "agent-manager-runtime.json"
    summary_path = artifact_dir / "manager-state.json"
    run_path = artifact_dir / "phase7-proof-mission-run.json"
    state_path = artifact_dir / "phase7-supervisor-state.sqlite3"

    run = _read_json(run_path, "Phase 7 mission run")
    config = _read_json(runtime_path, "Phase 7 runtime")
    store = SQLiteStateStore(state_path)
    source_sha, current = _validate_prepared_artifact(artifact_dir, run, config, store)
    if not os.environ.get(courier.KEY_ENV):
        raise Phase7CompletionError(f"{courier.KEY_ENV} is required to verify the returned laptop bundle")

    original_task = am.task_index(config).get(TASK_ID)
    if not isinstance(original_task, Mapping):
        raise Phase7CompletionError("laptop task is missing from runtime")
    producer_lease = original_task.get("lease_id")
    producer_dispatch = original_task.get("dispatch_id")
    producer_wait_digest = original_task.get("offline_dispatch_digest")
    if original_task.get("external_wait_state") != am.WAITING_EXTERNAL:
        raise Phase7CompletionError("laptop task is not waiting on an exported Courier result")

    staging = artifact_dir / ".phase7-completion-staging"
    staging.mkdir(parents=True, exist_ok=True)
    staging_runtime = staging / "agent-manager-runtime.json"
    staging_summary = staging / "manager-state.json"
    staging_events = staging / "manager-events.jsonl"
    prior_event_path = am.EVENT_PATH
    am.EVENT_PATH = staging_events
    try:
        working = deepcopy(config)
        courier.import_result(
            working,
            Path(returned_result),
            runtime_path=staging_runtime,
            summary_path=staging_summary,
        )
        task = am.task_index(working)[TASK_ID]
        producer_evidence = _validate_returned_laptop_evidence(task)
        if task.get("status") != "VERIFYING" or task.get("assigned_worker") != EXPECTED_VERIFIER:
            raise Phase7CompletionError("returned laptop result did not enter independent verification")
        if task.get("offline_result_bundle_ingested") is not True:
            raise Phase7CompletionError("Courier result ingestion marker is missing")
        result_bundle_digest = task.get("offline_result_bundle_digest")
        if not isinstance(result_bundle_digest, str) or len(result_bundle_digest) != 64:
            raise Phase7CompletionError("Courier result bundle digest is missing")

        producer_worker = _worker(working, EXPECTED_PRODUCER)
        verifier_worker = _worker(working, EXPECTED_VERIFIER)
        producer_domain = producer_worker.get("trust_domain")
        verifier_domain = verifier_worker.get("trust_domain")
        if not producer_domain or not verifier_domain or producer_domain == verifier_domain:
            raise Phase7CompletionError("laptop producer and verifier trust domains are not independent")
        if verifier_worker.get("verifier") is not True:
            raise Phase7CompletionError("assigned laptop verifier is not a verifier worker")

        zero_idle = _validate_zero_idle(run, working)
        verifier_tests = _run_independent_verifier()
        verifier_lease = task.get("lease_id")
        verifier_envelope = transport.envelope_for(task)
        task["correlation_id"] = verifier_envelope["correlation_id"]
        task["dispatch_id"] = verifier_envelope["dispatch_id"]
        task["dispatch_transport"] = verifier_envelope["transport"]
        task["dispatch_mode"] = "github-cloud-independent-laptop-verifier"
        task["dispatched_at"] = am.iso()
        if verifier_envelope["transport"] != "github-cloud":
            raise Phase7CompletionError("independent laptop verifier is not routed to GitHub cloud")

        verification_evidence = {
            "schema_version": VERIFY_SCHEMA,
            "accepted": True,
            "source_sha": source_sha,
            "task_id": TASK_ID,
            "producer_worker": EXPECTED_PRODUCER,
            "producer_trust_domain": producer_domain,
            "producer_lease_id": producer_lease,
            "producer_dispatch_id": producer_dispatch,
            "producer_dispatch_digest": producer_wait_digest,
            "producer_evidence_sha256": _digest(producer_evidence),
            "offline_result_bundle_digest": result_bundle_digest,
            "verifier_worker": EXPECTED_VERIFIER,
            "verifier_trust_domain": verifier_domain,
            "verifier_lease_id": verifier_lease,
            "verifier_dispatch_id": verifier_envelope["dispatch_id"],
            "verifier_transport": verifier_envelope["transport"],
            "verifier_suite": list(CLOUD_VERIFIER_SUITE),
            "verifier_tests": verifier_tests,
            "zero_idle_evidence_sha256": _digest(zero_idle),
            "checks": [
                "courier_hmac_and_result_digest_valid",
                "current_lease_and_dispatch_binding_valid",
                "windows_producer_identity_valid",
                "bounded_offline_workload_passed",
                "producer_and_verifier_trust_domains_independent",
                "cloud_verifier_regression_suite_passed",
                "zero_idle_overlap_bound_to_laptop_wait",
            ],
        }
        am.record_result(working, TASK_ID, EXPECTED_VERIFIER, "success", verification_evidence)
        completed_task = am.task_index(working)[TASK_ID]
        if completed_task.get("status") != "DONE" or completed_task.get("verification_evidence") != verification_evidence:
            raise Phase7CompletionError("laptop task did not reach verified DONE state")

        next_state = store.compare_and_swap(MISSION_ID, current.generation, working)
        final_summary = am.summarize(working)
        ledger = list(run.get("resource_ledger") or [])
        ledger.extend(
            [
                {
                    "task_id": TASK_ID,
                    "role": "producer_result",
                    "worker_id": EXPECTED_PRODUCER,
                    "resource": "windows-local",
                    "lease_id": producer_lease,
                    "correlation_id": completed_task.get("correlation_id"),
                    "dispatch_id": producer_dispatch,
                    "transport": "offline-courier",
                    "outcome": "success",
                    "result_bundle_sha256": result_bundle_digest,
                    "evidence_sha256": _digest(producer_evidence),
                },
                {
                    "task_id": TASK_ID,
                    "role": "verifier",
                    "worker_id": EXPECTED_VERIFIER,
                    "resource": "github-cloud-verifier",
                    "lease_id": verifier_lease,
                    "correlation_id": verifier_envelope["correlation_id"],
                    "dispatch_id": verifier_envelope["dispatch_id"],
                    "transport": verifier_envelope["transport"],
                    "outcome": "success",
                    "evidence_sha256": _digest(verification_evidence),
                },
            ]
        )
        completed_run = dict(run)
        completed_run.update(
            {
                "state_generation": next_state.generation,
                "state_sha256": next_state.payload_sha256,
                "manager_summary": final_summary,
                "resource_ledger": ledger,
                "courier": {
                    **dict(run["courier"]),
                    "status": "EXECUTED_AND_VERIFIED",
                    "result_bundle_sha256": result_bundle_digest,
                    "verification_evidence_sha256": _digest(verification_evidence),
                },
                "zero_idle_evidence": zero_idle,
                "hardware_proof_complete": True,
                "core_cloud_chain_complete": True,
            }
        )
        completed_run.pop("run_digest", None)
        completed_run["run_digest"] = _digest(completed_run)

        am.atomic_json(runtime_path, working)
        am.atomic_json(summary_path, final_summary)
        _write_json(run_path, completed_run)
        if staging_events.exists():
            existing = b""
            events_path = artifact_dir / "manager-events.jsonl"
            if events_path.exists():
                existing = events_path.read_bytes()
            staged = staging_events.read_bytes()
            combined = existing + staged
            events_tmp = events_path.with_suffix(".tmp")
            events_tmp.write_bytes(combined)
            os.replace(events_tmp, events_path)
        return completed_run
    finally:
        am.EVENT_PATH = prior_event_path
        for path in (staging_runtime, staging_summary, staging_events):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            staging.rmdir()
        except OSError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Complete a returned Phase 7 offline laptop proof with independent cloud verification")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--returned-result", required=True)
    args = parser.parse_args()
    completed = complete(Path(args.artifact_dir), Path(args.returned_result))
    print(json.dumps(completed, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
