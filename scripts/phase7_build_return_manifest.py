from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from scripts import phase7_return_package as package


def build_manifest(
    root: Path,
    *,
    session_id: str,
    source_sha: str,
    proof_run_id: int,
    prepared_artifact_name: str,
    created_at: str | None = None,
) -> dict:
    root = Path(root).resolve()
    if root.is_symlink() or not root.is_dir():
        raise package.Phase7ReturnPackageError("return package root must be a real directory")
    existing = {
        path.relative_to(root).as_posix(): path
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if set(existing) != package.PAYLOAD_FILES:
        raise package.Phase7ReturnPackageError("payload file inventory is incomplete or contains extras before manifest creation")
    if any(path.is_symlink() for path in root.rglob("*")):
        raise package.Phase7ReturnPackageError("return package may not contain symlinks")
    if not package.SESSION_RE.fullmatch(session_id):
        raise package.Phase7ReturnPackageError("return session id is invalid")
    source_sha = source_sha.lower()
    if not package.SHA_RE.fullmatch(source_sha):
        raise package.Phase7ReturnPackageError("return source SHA is invalid")
    if isinstance(proof_run_id, bool) or proof_run_id <= 0:
        raise package.Phase7ReturnPackageError("return proof run id is invalid")
    if prepared_artifact_name != f"nexus-phase7-proof-{source_sha}":
        raise package.Phase7ReturnPackageError("prepared artifact name is not exact-source bound")
    timestamp = created_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    package._parse_time(timestamp, "manifest.created_at")
    file_hashes = {relative: package._sha256(existing[relative]) for relative in sorted(existing)}
    payload = {
        "schema_version": package.SCHEMA,
        "session_id": session_id,
        "repository": package.REPO,
        "source_sha": source_sha,
        "proof_run_id": int(proof_run_id),
        "prepared_artifact_name": prepared_artifact_name,
        "created_at": timestamp,
        "files": file_hashes,
    }
    payload["package_sha256"] = hashlib.sha256(package._canonical(payload)).hexdigest()
    manifest_path = root / "manifest.json"
    temp = manifest_path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, manifest_path)
    package.validate_package(root, expected_source_sha=source_sha)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and validate a deterministic NEXUS Phase 7 return manifest")
    parser.add_argument("--package-root", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--proof-run-id", required=True, type=int)
    parser.add_argument("--prepared-artifact-name", required=True)
    parser.add_argument("--created-at")
    args = parser.parse_args()
    result = build_manifest(
        Path(args.package_root),
        session_id=args.session_id,
        source_sha=args.source_sha,
        proof_run_id=args.proof_run_id,
        prepared_artifact_name=args.prepared_artifact_name,
        created_at=args.created_at,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
