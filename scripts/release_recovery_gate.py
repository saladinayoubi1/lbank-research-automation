#!/usr/bin/env python3
"""Offline fail-closed gates for reproducibility and rollback evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

MAX_JSON_BYTES = 1_000_000
EXCLUDED_NAMES = {"artifact-manifest.sig", "artifact-manifest.pem"}
POLICY_VERSION = "ADR-0014-v1"
REPRO_SCHEMA = "nexus.reproducible-build-evidence.v1"


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
        if path.stat().st_nlink != 1:
            fail(f"hardlinked release output is not allowed: {path.relative_to(root).as_posix()}")
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
        fail(f"reproducible-build file set mismatch missing={sorted(left.keys()-right.keys())} extra={sorted(right.keys()-left.keys())}")
    mismatches = [name for name in left if left[name] != right[name]]
    if mismatches:
        fail("reproducible-build digest mismatch: " + ",".join(mismatches))
    return sorted(left)


def load_json(path: Path) -> Any:
    try:
        if path.is_symlink() or not path.is_file():
            fail(f"missing or unsafe file: {path.name}")
        if path.stat().st_size > MAX_JSON_BYTES:
            fail(f"JSON exceeds maximum size: {path.name}")
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing required file: {path.name}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.name}: {exc.msg}")


def valid_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def valid_commit(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def safe_evidence_path(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        fail("evidence_ref must be a canonical relative path")
    ref = PurePosixPath(value)
    if ref.is_absolute() or ".." in ref.parts or "." in ref.parts or str(ref) != value:
        fail("evidence_ref must be a canonical relative path")
    candidate = root.joinpath(*ref.parts)
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        fail("evidence_ref escapes rollback record directory")
    if candidate.is_symlink() or not candidate.is_file() or candidate.stat().st_nlink != 1:
        fail("rollback evidence is missing or unsafe")
    return candidate


def verify_reproducibility_record(path: Path) -> list[str]:
    record = load_json(path)
    expected_keys = {
        "schema", "policy_version", "production_claim", "source_commit",
        "build_instructions_sha256", "dependency_lock_sha256", "toolchain_sha256", "attempts",
    }
    if not isinstance(record, dict) or set(record) != expected_keys or record.get("schema") != REPRO_SCHEMA:
        fail("reproducibility record schema mismatch")
    if record.get("policy_version") != POLICY_VERSION or record.get("production_claim") is not False:
        fail("reproducibility record must remain bounded and non-production")
    if not valid_commit(record.get("source_commit")):
        fail("reproducibility source_commit must be lowercase 40-character SHA")
    for field in ("build_instructions_sha256", "dependency_lock_sha256", "toolchain_sha256"):
        if not valid_digest(record.get(field)):
            fail(f"{field} must be lowercase SHA-256")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not 2 <= len(attempts) <= 10:
        fail("reproducibility record requires two to ten build attempts")
    builders: set[str] = set()
    runs: set[int] = set()
    refs: set[str] = set()
    output_digests: set[str] = set()
    attempt_keys = {"builder_identity", "workflow_run_id", "clean_environment", "manifest_ref", "manifest_sha256", "artifact_count"}
    for attempt in attempts:
        if not isinstance(attempt, dict) or set(attempt) != attempt_keys:
            fail("reproducibility attempt schema mismatch")
        builder = attempt.get("builder_identity")
        run_id = attempt.get("workflow_run_id")
        ref = attempt.get("manifest_ref")
        if not isinstance(builder, str) or not builder.strip() or len(builder) > 200:
            fail("builder_identity is required")
        if not isinstance(run_id, int) or isinstance(run_id, bool) or run_id <= 0:
            fail("workflow_run_id must be a positive integer")
        if attempt.get("clean_environment") is not True:
            fail("each build attempt must declare a clean environment")
        if not isinstance(ref, str) or ref in refs:
            fail("build attempts require distinct manifest references")
        manifest = safe_evidence_path(path.parent, ref)
        digest = attempt.get("manifest_sha256")
        if not valid_digest(digest) or sha256(manifest) != digest:
            fail("build manifest digest mismatch")
        count = attempt.get("artifact_count")
        if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
            fail("artifact_count must be a positive integer")
        builders.add(builder)
        runs.add(run_id)
        refs.add(ref)
        output_digests.add(digest)
    if len(builders) != len(attempts) or len(runs) != len(attempts):
        fail("build attempts must use distinct builders and workflow runs")
    if len(output_digests) != 1:
        fail("independent build manifests are not byte-identical")
    return ["fixed-inputs", "clean-builds", "independent-builders", "distinct-runs", "manifest-identity", "non-production"]


def verify_rollback_record(path: Path) -> list[str]:
    record = load_json(path)
    if not isinstance(record, dict) or record.get("schema_version") != 2:
        fail("rollback record must use schema_version 2")
    if record.get("policy_version") != POLICY_VERSION:
        fail("unsupported rollback policy_version")
    if record.get("authorized") is not False:
        fail("rollback record must remain unauthorized until explicit production approval")

    current = record.get("current")
    previous = record.get("previous_valid")
    if not isinstance(current, dict) or not isinstance(previous, dict):
        fail("rollback record requires current and previous_valid objects")
    for label, item in (("current", current), ("previous_valid", previous)):
        if not isinstance(item.get("version"), str) or not item["version"].strip():
            fail(f"{label} version is required")
        if not valid_digest(item.get("manifest_sha256")):
            fail(f"{label} manifest_sha256 must be lowercase SHA-256")
        if not valid_commit(item.get("source_commit")):
            fail(f"{label} source_commit must be lowercase 40-character SHA")
        if not isinstance(item.get("workflow_run_id"), int) or item["workflow_run_id"] <= 0:
            fail(f"{label} workflow_run_id must be a positive integer")
    if current["version"] == previous["version"] or current["manifest_sha256"] == previous["manifest_sha256"]:
        fail("rollback target must differ from current release")

    evidence = safe_evidence_path(path.parent, record.get("evidence_ref"))
    expected = record.get("evidence_sha256")
    if not valid_digest(expected) or sha256(evidence) != expected:
        fail("rollback evidence digest mismatch")
    proof = load_json(evidence)
    if not isinstance(proof, dict):
        fail("rollback evidence must be an object")
    if proof.get("policy_version") != POLICY_VERSION:
        fail("rollback evidence policy mismatch")
    if proof.get("current_manifest_sha256") != current["manifest_sha256"]:
        fail("rollback evidence current manifest mismatch")
    if proof.get("previous_manifest_sha256") != previous["manifest_sha256"]:
        fail("rollback evidence previous manifest mismatch")
    if proof.get("schema_test_passed") is not True or proof.get("rollback_test_passed") is not True:
        fail("rollback evidence must record successful schema and rollback tests")
    return ["current", "previous-valid", "source-workflow-binding", "evidence-binding", "unauthorized-by-default"]


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    reproducible = subparsers.add_parser("compare-outputs")
    reproducible.add_argument("first", type=Path)
    reproducible.add_argument("second", type=Path)
    rollback = subparsers.add_parser("verify-rollback")
    rollback.add_argument("record", type=Path)
    evidence = subparsers.add_parser("verify-reproducibility")
    evidence.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "compare-outputs":
            print("REPRODUCIBLE_BUILD=PASS files=" + ",".join(compare_outputs(args.first, args.second)))
        elif args.command == "verify-rollback":
            print("ROLLBACK_GATE=PASS checks=" + ",".join(verify_rollback_record(args.record)))
        else:
            print("REPRODUCIBILITY_EVIDENCE_GATE=PASS checks=" + ",".join(verify_reproducibility_record(args.record)))
    except ValueError as exc:
        print(f"RELEASE_RECOVERY_GATE=BLOCKED reason={exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
