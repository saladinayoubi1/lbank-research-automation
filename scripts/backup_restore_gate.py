#!/usr/bin/env python3
"""Offline fail-closed verification for backup/restore drill evidence.

This validates bounded evidence only. It does not create backups, access storage,
manage credentials, authorize production recovery, or prove disaster recovery.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 1024 * 1024
REQUIRED_SCOPE = {"artifacts", "release_metadata", "configuration", "operational_state"}


def fail(message: str) -> None:
    raise ValueError(message)


def load_json(path: Path) -> Any:
    if not path.is_file():
        fail(f"missing drill evidence: {path.name}")
    if path.stat().st_size > MAX_JSON_BYTES:
        fail("drill evidence exceeds size limit")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {exc.msg}")


def parse_time(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        fail(f"{field} must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail(f"{field} must be RFC3339 UTC")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(evidence_path: Path, restored_root: Path) -> list[str]:
    data = load_json(evidence_path)
    if not isinstance(data, dict):
        fail("drill evidence must be an object")

    backup_id = data.get("backup_id")
    if not isinstance(backup_id, str) or not backup_id:
        fail("backup_id is required")
    if data.get("independent_storage") is not True:
        fail("independent storage evidence is required")
    if data.get("encryption_verified") is not True:
        fail("backup encryption verification is required")
    if not isinstance(data.get("key_owner"), str) or not data["key_owner"]:
        fail("key owner is required")
    retention_days = data.get("retention_days")
    if not isinstance(retention_days, int) or retention_days < 1:
        fail("positive retention_days is required")

    start = parse_time(data.get("restore_started_at"), "restore_started_at")
    end = parse_time(data.get("restore_completed_at"), "restore_completed_at")
    backup_time = parse_time(data.get("backup_created_at"), "backup_created_at")
    if not backup_time <= start <= end:
        fail("backup and restore timestamps are inconsistent")

    rpo_target = data.get("rpo_target_seconds")
    rto_target = data.get("rto_target_seconds")
    if not isinstance(rpo_target, int) or rpo_target < 0:
        fail("valid RPO target is required")
    if not isinstance(rto_target, int) or rto_target < 1:
        fail("valid RTO target is required")
    measured_rpo = int((start - backup_time).total_seconds())
    measured_rto = int((end - start).total_seconds())
    if measured_rpo > rpo_target:
        fail("RPO target not met")
    if measured_rto > rto_target:
        fail("RTO target not met")

    scope = data.get("scope")
    if not isinstance(scope, list) or set(scope) != REQUIRED_SCOPE:
        fail("restore scope is incomplete or unexpected")
    if data.get("clean_environment") is not True:
        fail("clean-environment restore is required")
    if data.get("corruption_test_passed") is not True:
        fail("corruption test evidence is required")
    if data.get("missing_backup_test_passed") is not True:
        fail("missing-backup test evidence is required")
    if data.get("target_verification_passed") is not True:
        fail("target-side verification is required")
    if data.get("production_authorized") is not False:
        fail("repository evidence must not preauthorize production recovery")

    files = data.get("restored_files")
    if not isinstance(files, list) or not files:
        fail("restored_files must be non-empty")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            fail("restored file entry must be an object")
        name = item.get("path")
        digest = item.get("sha256")
        size = item.get("size")
        if not isinstance(name, str) or not name or Path(name).is_absolute() or ".." in Path(name).parts:
            fail("restored path must be a safe relative path")
        if name in seen:
            fail(f"duplicate restored path: {name}")
        seen.add(name)
        target = restored_root / name
        if not target.is_file() or target.is_symlink():
            fail(f"restored file missing or unsupported: {name}")
        if not isinstance(digest, str) or len(digest) != 64:
            fail(f"invalid restored digest: {name}")
        if sha256(target) != digest:
            fail(f"restored digest mismatch: {name}")
        if not isinstance(size, int) or size < 0 or target.stat().st_size != size:
            fail(f"restored size mismatch: {name}")

    return ["backup-metadata", "restore-integrity", "rpo", "rto", "negative-drills", "target-verification"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("restored_root", type=Path)
    args = parser.parse_args()
    try:
        checks = verify(args.evidence, args.restored_root)
    except ValueError as exc:
        print(f"BACKUP_RESTORE_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    print("BACKUP_RESTORE_GATE=PASS checks=" + ",".join(checks))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
