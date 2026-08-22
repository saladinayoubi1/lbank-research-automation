#!/usr/bin/env python3
"""Fail-closed verification for bounded backup/restore drill evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any

MAX_JSON_BYTES = 1024 * 1024
MAX_EVIDENCE_AGE = timedelta(days=30)
POLICY_VERSION = "ADR-0015-v1"
REQUIRED_SCOPE = {"artifacts", "release_metadata", "configuration", "operational_state"}
HEX = set("0123456789abcdef")


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    if not path.is_file() or path.is_symlink():
        fail(f"missing or unsafe evidence file: {path.name}")
    if path.stat().st_size > MAX_JSON_BYTES:
        fail("evidence exceeds size limit")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc.msg}")


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail(f"{field} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        fail(f"{field} must be RFC3339 UTC")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in HEX for c in value)


def safe_evidence_path(root: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        fail("backup evidence_ref must be a canonical relative path")
    ref = PurePosixPath(value)
    if ref.is_absolute() or ".." in ref.parts or "." in ref.parts or str(ref) != value:
        fail("backup evidence_ref must be a canonical relative path")
    candidate = root.joinpath(*ref.parts)
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        fail("backup evidence artifact escapes evidence root")
    if not candidate.is_file() or candidate.is_symlink() or candidate.stat().st_nlink != 1:
        fail("backup evidence artifact is missing or unsafe")
    return candidate


def verify(evidence_path: Path, restored_root: Path, *, now: datetime | None = None) -> list[str]:
    data = load_json(evidence_path)
    expected_root = {
        "schema_version", "policy_version", "source_commit", "workflow_run_id", "backup_id",
        "backup_evidence_ref", "backup_evidence_sha256", "restore_started_at", "restore_completed_at",
        "rpo_target_seconds", "rto_target_seconds", "scope", "clean_environment",
        "corruption_test_passed", "missing_backup_test_passed", "target_verification_passed",
        "production_authorized", "restored_files",
    }
    if not isinstance(data, dict) or set(data) != expected_root or data.get("schema_version") != 2:
        fail("drill evidence must use schema_version 2")
    if data.get("policy_version") != POLICY_VERSION:
        fail("unsupported policy_version")
    source_commit = data.get("source_commit")
    if not isinstance(source_commit, str) or len(source_commit) != 40 or any(c not in HEX for c in source_commit):
        fail("source_commit must be lowercase 40-character SHA")
    if not isinstance(data.get("workflow_run_id"), int) or data["workflow_run_id"] <= 0:
        fail("workflow_run_id must be a positive integer")
    if data.get("production_authorized") is not False:
        fail("repository evidence must not preauthorize production recovery")

    if not restored_root.is_dir() or restored_root.is_symlink():
        fail("restored root must be a real directory")
    root = restored_root.resolve()

    backup_id = data.get("backup_id")
    if not isinstance(backup_id, str) or not backup_id:
        fail("backup_id is required")
    artifact = safe_evidence_path(evidence_path.parent, data.get("backup_evidence_ref"))
    expected = data.get("backup_evidence_sha256")
    raw_proof = artifact.read_bytes()
    if not valid_sha256(expected) or hashlib.sha256(raw_proof).hexdigest() != expected:
        fail("backup evidence digest mismatch")
    try:
        proof = json.loads(raw_proof.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid bound backup evidence JSON: {exc}")
    proof_keys = {"backup_id", "independent_storage", "encryption_verified", "retention_verified", "storage_object_version", "key_owner", "retention_days", "backup_created_at"}
    if not isinstance(proof, dict) or set(proof) != proof_keys:
        fail("backup evidence artifact must be an object")
    if proof.get("backup_id") != backup_id:
        fail("backup evidence backup_id mismatch")
    for key in ("independent_storage", "encryption_verified", "retention_verified"):
        if proof.get(key) is not True:
            fail(f"backup evidence {key} must be explicitly true")
    if not isinstance(proof.get("storage_object_version"), str) or not proof["storage_object_version"]:
        fail("backup evidence storage_object_version is required")
    if not isinstance(proof.get("key_owner"), str) or not proof["key_owner"]:
        fail("backup evidence key_owner is required")
    retention_days = proof.get("retention_days")
    if not isinstance(retention_days, int) or isinstance(retention_days, bool) or retention_days < 1:
        fail("positive retention_days is required")

    start = parse_time(data.get("restore_started_at"), "restore_started_at")
    end = parse_time(data.get("restore_completed_at"), "restore_completed_at")
    backup_time = parse_time(proof.get("backup_created_at"), "backup_created_at")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if not backup_time <= start <= end:
        fail("backup and restore timestamps are inconsistent")
    if end > current:
        fail("restore_completed_at cannot be in the future")
    if current - end > MAX_EVIDENCE_AGE:
        fail("backup/restore evidence is stale")

    rpo_target = data.get("rpo_target_seconds")
    rto_target = data.get("rto_target_seconds")
    if not isinstance(rpo_target, int) or isinstance(rpo_target, bool) or rpo_target < 0:
        fail("valid RPO target is required")
    if not isinstance(rto_target, int) or isinstance(rto_target, bool) or rto_target < 1:
        fail("valid RTO target is required")
    if int((start - backup_time).total_seconds()) > rpo_target:
        fail("RPO target not met")
    if int((end - start).total_seconds()) > rto_target:
        fail("RTO target not met")

    scope = data.get("scope")
    if not isinstance(scope, list) or any(not isinstance(x, str) for x in scope) or len(scope) != len(set(scope)) or set(scope) != REQUIRED_SCOPE:
        fail("restore scope is incomplete, duplicated, or unexpected")
    for key in ("clean_environment", "corruption_test_passed", "missing_backup_test_passed", "target_verification_passed"):
        if data.get(key) is not True:
            fail(f"{key} must be explicitly true")

    files = data.get("restored_files")
    if not isinstance(files, list) or not files:
        fail("restored_files must be non-empty")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            fail("restored file entry must be an object")
        name, digest, size = item.get("path"), item.get("sha256"), item.get("size")
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            fail("restored path must be a safe relative path")
        if name in seen:
            fail(f"duplicate restored path: {name}")
        seen.add(name)
        target = restored_root / name
        resolved = target.resolve(strict=False)
        if root not in resolved.parents:
            fail(f"restored path escapes root: {name}")
        if not target.is_file() or target.is_symlink() or target.stat().st_nlink != 1:
            fail(f"restored file missing or unsupported: {name}")
        if not valid_sha256(digest):
            fail(f"invalid restored digest: {name}")
        if sha256(target) != digest:
            fail(f"restored digest mismatch: {name}")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0 or target.stat().st_size != size:
            fail(f"restored size mismatch: {name}")

    return ["source-workflow-binding", "backup-artifact-binding", "restore-integrity", "freshness", "rpo", "rto", "negative-drills", "target-verification", "production-deny"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("restored_root", type=Path)
    args = parser.parse_args()
    try:
        print("BACKUP_RESTORE_GATE=PASS checks=" + ",".join(verify(args.evidence, args.restored_root)))
    except ValueError as exc:
        print(f"BACKUP_RESTORE_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
