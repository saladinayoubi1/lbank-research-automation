"""Deterministic SHA-256 artifact manifests with fail-closed verification.

This module is intentionally dependency-free. It proves byte integrity against a
versioned manifest; it does not prove signer identity, trusted provenance, or
reproducible correspondence to source code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

MANIFEST_VERSION = 1


class ArtifactIntegrityError(RuntimeError):
    """Artifact manifest creation or verification failed."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_relative(path: Path, root: Path) -> str:
    resolved_root = root.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    try:
        relative = resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise ArtifactIntegrityError(f"artifact escapes root: {path}") from exc
    return relative.as_posix()


def build_manifest(root: Path, files: Iterable[Path]) -> dict:
    root = root.resolve(strict=True)
    entries = []
    seen: set[str] = set()
    for candidate in files:
        path = candidate if candidate.is_absolute() else root / candidate
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise ArtifactIntegrityError(f"artifact must be a regular non-symlink file: {candidate}")
        relative = _normalize_relative(path, root)
        if relative in seen:
            raise ArtifactIntegrityError(f"duplicate artifact path: {relative}")
        seen.add(relative)
        stat = path.stat()
        entries.append({
            "path": relative,
            "size": stat.st_size,
            "sha256": _sha256(path),
        })
    entries.sort(key=lambda item: item["path"])
    if not entries:
        raise ArtifactIntegrityError("manifest requires at least one artifact")
    return {
        "schema": "nexus-artifact-integrity",
        "version": MANIFEST_VERSION,
        "algorithm": "sha256",
        "artifacts": entries,
    }


def write_manifest(root: Path, files: Iterable[Path], output: Path) -> dict:
    manifest = build_manifest(root, files)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ArtifactIntegrityError("manifest is unreadable or invalid JSON") from exc
    if manifest.get("schema") != "nexus-artifact-integrity":
        raise ArtifactIntegrityError("unsupported manifest schema")
    if manifest.get("version") != MANIFEST_VERSION:
        raise ArtifactIntegrityError("unsupported manifest version")
    if manifest.get("algorithm") != "sha256":
        raise ArtifactIntegrityError("unsupported digest algorithm")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ArtifactIntegrityError("manifest artifact list is missing or empty")
    return manifest


def verify_manifest(root: Path, manifest_path: Path) -> None:
    root = root.resolve(strict=True)
    manifest = load_manifest(manifest_path)
    expected_paths: set[str] = set()
    for entry in manifest["artifacts"]:
        if not isinstance(entry, dict):
            raise ArtifactIntegrityError("invalid artifact entry")
        relative = entry.get("path")
        size = entry.get("size")
        expected_digest = entry.get("sha256")
        if not isinstance(relative, str) or not relative or relative.startswith("/"):
            raise ArtifactIntegrityError("invalid artifact path")
        if relative in expected_paths:
            raise ArtifactIntegrityError(f"duplicate manifest path: {relative}")
        expected_paths.add(relative)
        path = root / relative
        if not path.exists() or not path.is_file() or path.is_symlink():
            raise ArtifactIntegrityError(f"artifact missing or invalid: {relative}")
        normalized = _normalize_relative(path, root)
        if normalized != relative:
            raise ArtifactIntegrityError(f"artifact path is not canonical: {relative}")
        stat = path.stat()
        if stat.st_size != size:
            raise ArtifactIntegrityError(f"artifact size mismatch: {relative}")
        actual_digest = _sha256(path)
        if actual_digest != expected_digest:
            raise ArtifactIntegrityError(f"artifact digest mismatch: {relative}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("files", nargs="+", type=Path)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "create":
        write_manifest(args.root, args.files, args.output)
    else:
        verify_manifest(args.root, args.manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
