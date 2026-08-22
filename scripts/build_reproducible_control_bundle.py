#!/usr/bin/env python3
"""Build a deterministic, non-production recovery-control bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

FILES = (
    "scripts/release_gate.py",
    "scripts/release_recovery_gate.py",
    "scripts/disaster_recovery_gate.py",
    "scripts/backup_restore_gate.py",
    "docs/adr/0014-bind-reproducibility-and-rollback-evidence.md",
)
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path, output: Path, manifest: Path, source_commit: str) -> None:
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("source_commit must be a lowercase 40-character SHA")
    entries: list[dict[str, object]] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        metadata = (json.dumps({"production": False, "source_commit": source_commit}, sort_keys=True) + "\n").encode()
        info = zipfile.ZipInfo("BUILD-METADATA.json", FIXED_TIME)
        info.external_attr = 0o100644 << 16
        archive.writestr(info, metadata)
        for relative in FILES:
            path = root / relative
            if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
                raise ValueError(f"unsafe bundle input: {relative}")
            payload = path.read_bytes()
            info = zipfile.ZipInfo(relative, FIXED_TIME)
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
            entries.append({"path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)})
    result = {
        "schema": "nexus.recovery-control-bundle.v1",
        "production": False,
        "source_commit": source_commit,
        "bundle_sha256": digest(output),
        "bundle_size": output.stat().st_size,
        "inputs": entries,
    }
    manifest.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    try:
        build(args.root, args.output, args.manifest, args.source_commit)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
