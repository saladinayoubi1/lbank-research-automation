#!/usr/bin/env python3
"""Exercise quarantine and restore without production authority."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def drill(valid: Path, workspace: Path, evidence: Path) -> None:
    if valid.is_symlink() or not valid.is_file() or valid.stat().st_nlink != 1:
        raise ValueError("valid bundle is missing or unsafe")
    workspace.mkdir(parents=True, exist_ok=False)
    previous = workspace / "previous-valid.zip"
    candidate = workspace / "candidate.zip"
    quarantine = workspace / "quarantine" / "candidate.zip"
    restored = workspace / "restored.zip"
    shutil.copyfile(valid, previous)
    shutil.copyfile(valid, candidate)
    with candidate.open("ab") as handle:
        handle.write(b"tampered")
    corruption_rejected = sha(candidate) != sha(previous)
    if not corruption_rejected:
        raise ValueError("corrupt candidate was not rejected")
    quarantine.parent.mkdir()
    candidate.replace(quarantine)
    shutil.copyfile(previous, restored)
    restore_verified = sha(restored) == sha(previous)
    if not restore_verified:
        raise ValueError("restore digest mismatch")
    result = {
        "schema": "nexus.nonproduction-rollback-drill.v1",
        "production": False,
        "production_authorized": False,
        "previous_valid_sha256": sha(previous),
        "quarantined_candidate_sha256": sha(quarantine),
        "restored_sha256": sha(restored),
        "corruption_rejected": corruption_rejected,
        "quarantine_preserved": quarantine.is_file(),
        "restore_verified": restore_verified,
    }
    evidence.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--valid", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    try:
        drill(args.valid, args.workspace, args.evidence)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
