from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts import phase7_return_package as package


def _normalize_offline_network_proof(root: Path) -> None:
    """Normalize the Windows-generated proof before byte-addressed packaging.

    Windows PowerShell 5.1 may emit UTF-8 BOM and CRLF. Git for Windows may
    then normalize line endings while committing the data-only return branch,
    which would make a manifest digest computed before `git add` disagree with
    the exact blob verified on GitHub. Normalize only the transport
    representation here; the proof schema, timestamps, result hash, reboot and
    network observations are validated immediately afterwards.
    """

    path = root / "returned/offline-network-proof.json"
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise package.Phase7ReturnPackageError("offline network proof JSON is invalid before normalization") from exc
    if not isinstance(value, dict):
        raise package.Phase7ReturnPackageError("offline network proof root must be an object")
    normalized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temp = path.with_suffix(".normalize.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(normalized)
    os.replace(temp, path)


def _ensure_windows_return_branch_delete_target(
    *,
    session_id: str,
    source_sha: str,
    repo_root: Path | None = None,
    platform_name: str | None = None,
) -> bool:
    """Seed the local branch that SubmitReturn intentionally deletes/recreates.

    The PowerShell handoff deletes the local return branch before creating its
    isolated worktree. On a first-ever return that branch does not exist and
    `git branch -D` exits non-zero. Seed a harmless local pointer at the already
    verified source SHA so the existing delete/recreate contract remains
    fail-closed and deterministic. This compatibility path is Windows-only.
    """

    platform = os.name if platform_name is None else platform_name
    if platform != "nt":
        return False
    if not package.SESSION_RE.fullmatch(session_id):
        raise package.Phase7ReturnPackageError("return session id is invalid")
    source_sha = source_sha.lower()
    if not package.SHA_RE.fullmatch(source_sha):
        raise package.Phase7ReturnPackageError("return source SHA is invalid")

    root = Path.cwd().resolve() if repo_root is None else Path(repo_root).resolve()
    if not (root / ".git").exists():
        raise package.Phase7ReturnPackageError("Windows return branch preflight requires the repository root")

    branch = f"phase7/return-{session_id}"
    source_ref = f"{source_sha}^{{commit}}"
    verify = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", source_ref],
        text=True,
        capture_output=True,
        check=False,
    )
    if verify.returncode != 0:
        raise package.Phase7ReturnPackageError("Windows return branch preflight source commit is unavailable")

    ref = f"refs/heads/{branch}"
    exists = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--verify", "--quiet", ref],
        text=True,
        capture_output=True,
        check=False,
    )
    if exists.returncode == 0:
        return False
    if exists.returncode != 1:
        raise package.Phase7ReturnPackageError("Windows return branch preflight could not inspect the local branch")

    created = subprocess.run(
        ["git", "-C", str(root), "branch", branch, source_sha],
        text=True,
        capture_output=True,
        check=False,
    )
    if created.returncode != 0:
        detail = (created.stderr or created.stdout or "unknown git error").strip()
        raise package.Phase7ReturnPackageError(f"Windows return branch preflight failed: {detail}")
    return True


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

    _normalize_offline_network_proof(root)
    existing["returned/offline-network-proof.json"] = root / "returned/offline-network-proof.json"

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
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
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
    _ensure_windows_return_branch_delete_target(
        session_id=args.session_id,
        source_sha=args.source_sha,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
