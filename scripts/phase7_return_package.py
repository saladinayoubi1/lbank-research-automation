from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

import agent_manager as am
import phase7_e2e_proof

SCHEMA = "nexus.phase7-return-package.v1"
NETWORK_SCHEMA = "nexus.phase7-offline-network-proof.v1"
REPO = "saladinayoubi1/lbank-research-automation"
TASK_ID = "P7-LAPTOP-CANONICAL"
SESSION_RE = re.compile(r"^p7-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_PACKAGE_BYTES = 12_000_000
MAX_FILE_BYTES = 6_000_000

PREPARED_FILES = {
    "prepared/agent-manager-runtime.json",
    "prepared/manager-state.json",
    "prepared/phase7-supervisor-state.sqlite3",
    "prepared/manager-events.jsonl",
    "prepared/phase7-e2e-proof.json",
    "prepared/phase7-proof-mission-run.json",
    "prepared/courier/phase7-laptop-dispatch.json",
}
RETURNED_FILES = {
    "returned/phase7-laptop-result.json",
    "returned/offline-network-proof.json",
}
PAYLOAD_FILES = PREPARED_FILES | RETURNED_FILES


class Phase7ReturnPackageError(ValueError):
    pass


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise Phase7ReturnPackageError(f"{label} is unavailable") from exc
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise Phase7ReturnPackageError(f"{label} size is outside bounds")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Phase7ReturnPackageError(f"{label} JSON is invalid") from exc
    if not isinstance(value, dict):
        raise Phase7ReturnPackageError(f"{label} root must be an object")
    return value


def _parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise Phase7ReturnPackageError(f"{field} timestamp is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Phase7ReturnPackageError(f"{field} timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise Phase7ReturnPackageError(f"{field} timestamp must be timezone-aware")
    return parsed


def _assert_regular_tree(root: Path) -> dict[str, Path]:
    if root.is_symlink() or not root.is_dir():
        raise Phase7ReturnPackageError("return package root must be a real directory")
    files: dict[str, Path] = {}
    total = 0
    for path in root.rglob("*"):
        if path.is_symlink():
            raise Phase7ReturnPackageError("return package may not contain symlinks")
        if path.is_dir():
            continue
        if not path.is_file():
            raise Phase7ReturnPackageError("return package contains a non-regular entry")
        relative = path.relative_to(root).as_posix()
        size = path.stat().st_size
        if size <= 0 or size > MAX_FILE_BYTES:
            raise Phase7ReturnPackageError(f"return file size is outside bounds: {relative}")
        total += size
        files[relative] = path
    if total > MAX_PACKAGE_BYTES:
        raise Phase7ReturnPackageError("return package exceeds bounded total size")
    expected = PAYLOAD_FILES | {"manifest.json"}
    if set(files) != expected:
        missing = sorted(expected - set(files))
        extra = sorted(set(files) - expected)
        raise Phase7ReturnPackageError(f"return package file set mismatch; missing={missing}; extra={extra}")
    return files


def _validate_manifest(root: Path, files: Mapping[str, Path]) -> dict[str, Any]:
    manifest = _read_json(files["manifest.json"], "return manifest")
    required = {
        "schema_version", "session_id", "repository", "source_sha", "proof_run_id",
        "prepared_artifact_name", "created_at", "files", "package_sha256",
    }
    if set(manifest) != required or manifest.get("schema_version") != SCHEMA:
        raise Phase7ReturnPackageError("return manifest schema mismatch")
    session_id = manifest.get("session_id")
    source_sha = manifest.get("source_sha")
    if not isinstance(session_id, str) or not SESSION_RE.fullmatch(session_id):
        raise Phase7ReturnPackageError("return session id is invalid")
    if manifest.get("repository") != REPO:
        raise Phase7ReturnPackageError("return repository identity mismatch")
    if not isinstance(source_sha, str) or not SHA_RE.fullmatch(source_sha):
        raise Phase7ReturnPackageError("return source SHA is invalid")
    run_id = manifest.get("proof_run_id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise Phase7ReturnPackageError("return proof run id is invalid")
    artifact_name = manifest.get("prepared_artifact_name")
    if artifact_name != f"nexus-phase7-proof-{source_sha}":
        raise Phase7ReturnPackageError("prepared artifact name is not exact-source bound")
    _parse_time(manifest.get("created_at"), "manifest.created_at")
    declared = manifest.get("files")
    if not isinstance(declared, dict) or set(declared) != PAYLOAD_FILES:
        raise Phase7ReturnPackageError("manifest file inventory mismatch")
    for relative in sorted(PAYLOAD_FILES):
        expected = declared.get(relative)
        if not isinstance(expected, str) or not HEX64_RE.fullmatch(expected):
            raise Phase7ReturnPackageError(f"manifest digest is invalid for {relative}")
        if _sha256(files[relative]) != expected:
            raise Phase7ReturnPackageError(f"manifest digest mismatch for {relative}")
    package_payload = {
        "schema_version": SCHEMA,
        "session_id": session_id,
        "repository": REPO,
        "source_sha": source_sha,
        "proof_run_id": run_id,
        "prepared_artifact_name": artifact_name,
        "created_at": manifest["created_at"],
        "files": {key: declared[key] for key in sorted(declared)},
    }
    claimed_package = manifest.get("package_sha256")
    if not isinstance(claimed_package, str) or not HEX64_RE.fullmatch(claimed_package):
        raise Phase7ReturnPackageError("package digest is invalid")
    actual_package = hashlib.sha256(_canonical(package_payload)).hexdigest()
    if actual_package != claimed_package:
        raise Phase7ReturnPackageError("package digest mismatch")
    return manifest


def _validate_prepared(root: Path, manifest: Mapping[str, Any]) -> None:
    source_sha = str(manifest["source_sha"])
    run = _read_json(root / "prepared/phase7-proof-mission-run.json", "prepared Proof Mission run")
    if run.get("schema_version") != "nexus.phase7-proof-mission-run.v1":
        raise Phase7ReturnPackageError("prepared Proof Mission schema mismatch")
    if run.get("source_sha") != source_sha:
        raise Phase7ReturnPackageError("prepared Proof Mission source SHA mismatch")
    if run.get("paper_only") is not True or run.get("live_trading_authority") is not False:
        raise Phase7ReturnPackageError("prepared Proof Mission widened authority")
    if run.get("core_cloud_chain_complete") is not True or run.get("hardware_proof_complete") is not False:
        raise Phase7ReturnPackageError("prepared Proof Mission completion state is invalid")
    courier = run.get("courier")
    if not isinstance(courier, Mapping) or courier.get("status") != "EXPORTED":
        raise Phase7ReturnPackageError("prepared Proof Mission lacks a real Courier export")
    if courier.get("task_id") != TASK_ID or courier.get("worker_id") != "windows-runner":
        raise Phase7ReturnPackageError("prepared Courier task identity mismatch")
    zero_idle = run.get("zero_idle_evidence")
    if not isinstance(zero_idle, Mapping) or zero_idle.get("rule") != "dispatch_independent_ready_work_while_other_resource_waits":
        raise Phase7ReturnPackageError("prepared Proof Mission lacks zero-idle overlap evidence")
    waits = zero_idle.get("overlapped_external_waits")
    if not isinstance(waits, list) or not any(isinstance(row, Mapping) and row.get("task_id") == TASK_ID for row in waits):
        raise Phase7ReturnPackageError("zero-idle evidence is not bound to the laptop wait")

    e2e = _read_json(root / "prepared/phase7-e2e-proof.json", "prepared E2E proof")
    phase7_e2e_proof.validate_proof(e2e, expected_source_sha=source_sha)
    if e2e.get("proof_digest") != run.get("e2e_proof_digest"):
        raise Phase7ReturnPackageError("prepared E2E proof digest mismatch")

    runtime = _read_json(root / "prepared/agent-manager-runtime.json", "prepared Agent Manager runtime")
    am.validate_config(runtime)
    task = am.task_index(runtime).get(TASK_ID)
    if not isinstance(task, Mapping):
        raise Phase7ReturnPackageError("prepared laptop task is missing")
    if task.get("assigned_worker") != "windows-runner" or task.get("dispatch_mode") != "offline-courier":
        raise Phase7ReturnPackageError("prepared laptop task is not an offline Courier dispatch")
    if task.get("external_wait_state") != am.WAITING_EXTERNAL:
        raise Phase7ReturnPackageError("prepared laptop task is not waiting externally")


def _validate_network_proof(root: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    proof = _read_json(root / "returned/offline-network-proof.json", "offline network proof")
    required = {
        "schema_version", "session_id", "source_sha", "prepared_at", "boot_time_utc",
        "reboot_after_prepare", "pre_execution", "execution_started_at", "execution_finished_at",
        "post_execution", "result_sha256", "observation_method",
    }
    if set(proof) != required or proof.get("schema_version") != NETWORK_SCHEMA:
        raise Phase7ReturnPackageError("offline network proof schema mismatch")
    if proof.get("session_id") != manifest.get("session_id") or proof.get("source_sha") != manifest.get("source_sha"):
        raise Phase7ReturnPackageError("offline network proof session/source mismatch")
    prepared_at = _parse_time(proof.get("prepared_at"), "offline.prepared_at")
    boot_at = _parse_time(proof.get("boot_time_utc"), "offline.boot_time_utc")
    started = _parse_time(proof.get("execution_started_at"), "offline.execution_started_at")
    finished = _parse_time(proof.get("execution_finished_at"), "offline.execution_finished_at")
    if proof.get("reboot_after_prepare") is not True or boot_at <= prepared_at:
        raise Phase7ReturnPackageError("offline proof does not show a reboot after preparation")
    if not (boot_at <= started <= finished):
        raise Phase7ReturnPackageError("offline execution timestamps are inconsistent")
    method = proof.get("observation_method")
    if method != "bounded_tcp_connect_dual_target_v1":
        raise Phase7ReturnPackageError("offline network observation method mismatch")
    for name in ("pre_execution", "post_execution"):
        observation = proof.get(name)
        if not isinstance(observation, Mapping) or observation.get("internet_unavailable") is not True:
            raise Phase7ReturnPackageError(f"{name} does not prove unavailable internet")
        _parse_time(observation.get("checked_at"), f"offline.{name}.checked_at")
        targets = observation.get("targets")
        if not isinstance(targets, list) or len(targets) != 2:
            raise Phase7ReturnPackageError(f"{name} must contain two network observations")
        for target in targets:
            if not isinstance(target, Mapping) or set(target) != {"host", "port", "reachable", "error"}:
                raise Phase7ReturnPackageError(f"{name} target schema mismatch")
            if target.get("reachable") is not False:
                raise Phase7ReturnPackageError(f"{name} observed reachable external network")
    result_hash = _sha256(root / "returned/phase7-laptop-result.json")
    if proof.get("result_sha256") != result_hash:
        raise Phase7ReturnPackageError("offline network proof is not bound to returned result")
    return proof


def _validate_return_result(root: Path) -> None:
    result = _read_json(root / "returned/phase7-laptop-result.json", "returned laptop result")
    if result.get("schema_version") != 1 or result.get("kind") != "nexus.offline-result.v1":
        raise Phase7ReturnPackageError("returned laptop bundle contract mismatch")
    embedded = result.get("result")
    if not isinstance(embedded, Mapping) or embedded.get("task_id") != TASK_ID:
        raise Phase7ReturnPackageError("returned laptop result task identity mismatch")
    if embedded.get("worker_id") != "windows-runner" or embedded.get("transport") != "windows":
        raise Phase7ReturnPackageError("returned laptop result worker/transport mismatch")


def validate_package(package_root: Path, *, expected_source_sha: str | None = None) -> dict[str, Any]:
    root = Path(package_root).resolve()
    files = _assert_regular_tree(root)
    manifest = _validate_manifest(root, files)
    if expected_source_sha is not None and manifest.get("source_sha") != expected_source_sha.lower():
        raise Phase7ReturnPackageError("return package source SHA is not the expected trusted source")
    _validate_prepared(root, manifest)
    _validate_return_result(root)
    network = _validate_network_proof(root, manifest)
    return {
        "schema_version": SCHEMA,
        "session_id": manifest["session_id"],
        "source_sha": manifest["source_sha"],
        "proof_run_id": manifest["proof_run_id"],
        "prepared_dir": str((root / "prepared").resolve()),
        "returned_result": str((root / "returned/phase7-laptop-result.json").resolve()),
        "offline_network_proof": str((root / "returned/offline-network-proof.json").resolve()),
        "offline_network_proof_sha256": _sha256(root / "returned/offline-network-proof.json"),
        "package_sha256": manifest["package_sha256"],
        "reboot_after_prepare": network["reboot_after_prepare"],
        "internet_unavailable_pre": network["pre_execution"]["internet_unavailable"],
        "internet_unavailable_post": network["post_execution"]["internet_unavailable"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a data-only NEXUS Phase 7 laptop return package")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--expected-source-sha")
    args = parser.parse_args()
    result = validate_package(Path(args.package_root), expected_source_sha=args.expected_source_sha)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
