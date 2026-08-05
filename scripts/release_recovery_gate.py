#!/usr/bin/env python3
"""Offline fail-closed gates for reproducibility and rollback metadata.

These checks compare two independently produced output directories and validate a
rollback record. They do not create releases, credentials, backups, signatures,
or production approvals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

MAX_JSON_BYTES = 1_000_000
EXCLUDED_NAMES = {"artifact-manifest.sig", "artifact-manifest.pem"}


def fail(message: str) -> None:
    raise ValueError(message)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path) -> dict[str, tuple[int, str]]:
    if not root.is_dir():
        fail(f"output directory does not exist: {root}")
    result: dict[str, tuple[int, str]] = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            fail(f"symlink is not allowed in release output: {path.relative_to(root).as_posix()}")
        if not path.is_file() or path.name in EXCLUDED_NAMES:
            continue
        relative = path.relative_to(root).as_posix()
        if relative in result:
            fail(f"duplicate normalized output path: {relative}")
        result[relative] = (path.stat().st_size, sha256(path))
    if not result:
        fail("release output must contain at least one file")
    return result


def compare_outputs(first: Path, second: Path) -> list[str]:
    left = snapshot(first)
    right = snapshot(second)
    if left.keys() != right.keys():
        missing = sorted(left.keys() - right.keys())
        extra = sorted(right.keys() - left.keys())
        fail(f"reproducible-build file set mismatch missing={missing} extra={extra}")
    mismatches = [name for name in left if left[name] != right[name]]
    if mismatches:
        fail("reproducible-build digest mismatch: " + ",".join(mismatches))
    return sorted(left)


def load_json(path: Path) -> Any:
    try:
        if path.stat().st_size > MAX_JSON_BYTES:
            fail(f"JSON exceeds maximum size: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing required file: {path.name}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.name}: {exc.msg}")


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def verify_rollback_record(path: Path) -> list[str]:
    record = load_json(path)
    if not isinstance(record, dict):
        fail("rollback record must be an object")
    current = record.get("current")
    previous = record.get("previous_valid")
    if not isinstance(current, dict) or not isinstance(previous, dict):
        fail("rollback record requires current and previous_valid objects")
    for label, item in (("current", current), ("previous_valid", previous)):
        version = item.get("version")
        digest = item.get("manifest_sha256")
        if not isinstance(version, str) or not version.strip():
            fail(f"{label} version is required")
        if not valid_digest(digest):
            fail(f"{label} manifest_sha256 must be lowercase SHA-256")
    if current["version"] == previous["version"]:
        fail("rollback target must differ from current version")
    if current["manifest_sha256"] == previous["manifest_sha256"]:
        fail("rollback target digest must differ from current digest")
    if record.get("authorized") is not False:
        fail("rollback record must remain unauthorized until explicit production approval")
    if record.get("schema_compatible") is not True:
        fail("rollback record must explicitly assert schema compatibility")
    return ["current", "previous-valid", "unauthorized-by-default", "schema-compatible"]


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    reproducible = subparsers.add_parser("compare-outputs")
    reproducible.add_argument("first", type=Path)
    reproducible.add_argument("second", type=Path)
    rollback = subparsers.add_parser("verify-rollback")
    rollback.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "compare-outputs":
            files = compare_outputs(args.first, args.second)
            print("REPRODUCIBLE_BUILD=PASS files=" + ",".join(files))
        else:
            checks = verify_rollback_record(args.record)
            print("ROLLBACK_GATE=PASS checks=" + ",".join(checks))
    except ValueError as exc:
        print(f"RELEASE_RECOVERY_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
