from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

import agent_manager as am
import agent_transport as at
from scripts import agent_task_executor as executor

RUNTIME_PATH = Path("data/agent_coordination/agent_manager_runtime.json")
SUMMARY_PATH = Path("data/agent_coordination/manager_state.json")
KEY_ENV = "NEXUS_OFFLINE_COURIER_KEY"
DISPATCH_KIND = "nexus.offline-dispatch.v1"
RESULT_KIND = "nexus.offline-result.v1"
MAX_BUNDLE_BYTES = 512_000
MIN_KEY_BYTES = 32
MAX_OFFLINE_LEASE_MINUTES = 24 * 60


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _key() -> bytes:
    value = os.environ.get(KEY_ENV)
    if not value:
        raise RuntimeError(f"{KEY_ENV} missing")
    raw = value.encode("utf-8")
    if len(raw) < MIN_KEY_BYTES:
        raise RuntimeError(f"{KEY_ENV} must contain at least {MIN_KEY_BYTES} bytes")
    return raw


def _seal(unsigned: dict[str, Any]) -> dict[str, Any]:
    signature = hmac.new(_key(), _canonical(unsigned), hashlib.sha256).hexdigest()
    return {**unsigned, "hmac_sha256": signature}


def _verify(bundle: dict[str, Any], *, kind: str, required_keys: set[str]) -> None:
    if not isinstance(bundle, dict) or set(bundle) != required_keys | {"hmac_sha256"}:
        raise ValueError("offline courier bundle schema mismatch")
    if bundle.get("schema_version") != 1 or bundle.get("kind") != kind:
        raise ValueError("unsupported offline courier bundle")
    signature = bundle.get("hmac_sha256")
    if not isinstance(signature, str) or len(signature) != 64:
        raise ValueError("offline courier signature is malformed")
    unsigned = {key: value for key, value in bundle.items() if key != "hmac_sha256"}
    expected = hmac.new(_key(), _canonical(unsigned), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("offline courier signature mismatch")


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    if len(raw) > MAX_BUNDLE_BYTES:
        raise ValueError("offline courier bundle exceeds bounded size")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("offline courier bundle JSON is malformed") from exc
    if not isinstance(value, dict):
        raise ValueError("offline courier bundle root must be an object")
    return value


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    os.replace(tmp, path)


def _load_runtime(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError("agent-manager runtime missing or malformed") from exc
    if not isinstance(value, dict):
        raise RuntimeError("agent-manager runtime must be an object")
    am.validate_config(value)
    return value


def _save_runtime(runtime_path: Path, summary_path: Path, config: dict[str, Any]) -> None:
    am.atomic_json(runtime_path, config)
    am.atomic_json(summary_path, am.summarize(config))


def _lease_minutes(config: dict[str, Any]) -> int:
    value = config.get("policy", {}).get("offline_courier_lease_minutes", 120)
    if isinstance(value, bool) or not isinstance(value, int) or value < 5 or value > MAX_OFFLINE_LEASE_MINUTES:
        raise ValueError("offline_courier_lease_minutes is outside bounded range")
    return value


def export_task(
    config: dict[str, Any],
    task_id: str,
    output: Path,
    *,
    runtime_path: Path = RUNTIME_PATH,
    summary_path: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    task = am.task_index(config).get(task_id)
    if task is None:
        raise ValueError("unknown task")
    if task.get("status") not in {"LEASED", "RUNNING"}:
        raise ValueError("offline task must hold an active lease")
    worker = task.get("assigned_worker")
    if worker not in at.offline_courier_workers(config):
        raise ValueError("task worker is not configured for offline courier")
    envelope = at.envelope_for(task)
    if envelope.get("transport") != "windows":
        raise ValueError("offline courier currently permits Windows transport only")
    expected_dispatch = envelope["dispatch_id"]
    prior_dispatch = task.get("dispatch_id")
    if prior_dispatch and prior_dispatch != expected_dispatch:
        raise ValueError("task already carries a different dispatch identity")
    payload_digest = _digest(envelope)
    prior_digest = task.get("offline_dispatch_digest")
    if prior_digest and prior_digest != payload_digest:
        raise ValueError("task already carries a different offline dispatch digest")

    created_at = task.get("offline_dispatch_bundle_created_at") or am.iso()
    unsigned = {
        "schema_version": 1,
        "kind": DISPATCH_KIND,
        "created_at": created_at,
        "payload_sha256": payload_digest,
        "payload": envelope,
    }
    bundle = _seal(unsigned)
    _atomic_write(output, bundle)

    now = am.utcnow()
    task["status"] = "RUNNING"
    task["correlation_id"] = envelope["correlation_id"]
    task["dispatch_id"] = expected_dispatch
    task["dispatch_transport"] = "windows"
    task["dispatch_mode"] = "offline-courier"
    task["dispatched_at"] = task.get("dispatched_at") or am.iso(now)
    task["offline_dispatch_digest"] = payload_digest
    task["offline_dispatch_bundle_created_at"] = created_at
    # An offline courier cannot send a live heartbeat. The bounded lease expiry is
    # therefore the fencing deadline; heartbeat is intentionally absent.
    task["heartbeat_at"] = None
    task["lease_expires_at"] = am.iso(now + timedelta(minutes=_lease_minutes(config)))
    _save_runtime(runtime_path, summary_path, config)
    am.emit(
        "offline_task_exported",
        task_id=task["id"],
        worker=worker,
        lease_id=task["lease_id"],
        dispatch_id=expected_dispatch,
        payload_sha256=payload_digest,
    )
    return bundle


def execute_bundle(dispatch_path: Path, output: Path) -> dict[str, Any]:
    bundle = _read_json(dispatch_path)
    _verify(
        bundle,
        kind=DISPATCH_KIND,
        required_keys={"schema_version", "kind", "created_at", "payload_sha256", "payload"},
    )
    payload = bundle["payload"]
    if not isinstance(payload, dict) or _digest(payload) != bundle.get("payload_sha256"):
        raise ValueError("offline dispatch payload digest mismatch")
    # Reuse the canonical executor decoder instead of maintaining a second schema.
    encoded = base64.urlsafe_b64encode(_canonical(payload)).decode("ascii")
    payload = executor.decode_payload(encoded)
    if payload.get("transport") != "windows":
        raise ValueError("offline executor accepts Windows transport only")
    result = executor.execute(payload, "windows")
    result_digest = _digest(result)
    unsigned = {
        "schema_version": 1,
        "kind": RESULT_KIND,
        "created_at": am.iso(),
        "source_dispatch_sha256": bundle["payload_sha256"],
        "result_sha256": result_digest,
        "result": result,
    }
    result_bundle = _seal(unsigned)
    _atomic_write(output, result_bundle)
    return result_bundle


def import_result(
    config: dict[str, Any],
    result_path: Path,
    *,
    runtime_path: Path = RUNTIME_PATH,
    summary_path: Path = SUMMARY_PATH,
) -> dict[str, Any]:
    bundle = _read_json(result_path)
    _verify(
        bundle,
        kind=RESULT_KIND,
        required_keys={
            "schema_version", "kind", "created_at", "source_dispatch_sha256", "result_sha256", "result"
        },
    )
    result = bundle["result"]
    if not isinstance(result, dict) or _digest(result) != bundle.get("result_sha256"):
        raise ValueError("offline result payload digest mismatch")
    task_id = result.get("task_id")
    task = am.task_index(config).get(task_id)
    if task is None:
        raise ValueError("offline result references unknown task")
    if task.get("dispatch_mode") != "offline-courier":
        raise ValueError("task was not dispatched through offline courier")
    if bundle.get("source_dispatch_sha256") != task.get("offline_dispatch_digest"):
        raise ValueError("offline result is not bound to current dispatch bundle")
    expiry = am.parse_time(task.get("lease_expires_at"))
    if expiry is None or expiry <= am.utcnow():
        raise ValueError("offline result arrived after lease expiry")
    at.ingest_result(config, task, result)
    task["offline_result_bundle_ingested"] = True
    task["offline_result_bundle_digest"] = bundle["result_sha256"]
    _save_runtime(runtime_path, summary_path, config)
    am.emit(
        "offline_result_ingested",
        task_id=task_id,
        source_dispatch_sha256=bundle["source_dispatch_sha256"],
        result_sha256=bundle["result_sha256"],
    )
    return bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Fenced HMAC-bound NEXUS offline Windows task courier")
    parser.add_argument("--runtime", default=str(RUNTIME_PATH))
    parser.add_argument("--summary", default=str(SUMMARY_PATH))
    sub = parser.add_subparsers(dest="command", required=True)

    export_parser = sub.add_parser("export", help="Export one leased Windows task for offline transfer")
    export_parser.add_argument("--task-id", required=True)
    export_parser.add_argument("--output", required=True)

    execute_parser = sub.add_parser("execute", help="Execute one transferred task on the offline laptop")
    execute_parser.add_argument("--input", required=True)
    execute_parser.add_argument("--output", required=True)

    import_parser = sub.add_parser("import", help="Import one transferred laptop result")
    import_parser.add_argument("--input", required=True)

    args = parser.parse_args()
    if args.command == "execute":
        result = execute_bundle(Path(args.input), Path(args.output))
        print(json.dumps({"outcome": result["result"]["outcome"], "result_sha256": result["result_sha256"]}, sort_keys=True))
        return 0 if result["result"]["outcome"] == "success" else 2

    runtime_path = Path(args.runtime)
    summary_path = Path(args.summary)
    config = _load_runtime(runtime_path)
    if args.command == "export":
        bundle = export_task(config, args.task_id, Path(args.output), runtime_path=runtime_path, summary_path=summary_path)
        print(json.dumps({"task_id": args.task_id, "payload_sha256": bundle["payload_sha256"]}, sort_keys=True))
        return 0
    bundle = import_result(config, Path(args.input), runtime_path=runtime_path, summary_path=summary_path)
    print(json.dumps({"task_id": bundle["result"]["task_id"], "result_sha256": bundle["result_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
