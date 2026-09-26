"""Fail-closed copy of a proven DISPOSABLE Electron clone; never an owner installer.

This command neither stops processes nor authenticates whether the disposable
clone is currently quiescent. Its receipt must never be used as actual-owner
activation or transactional-rollback evidence. Retain .INCOMPLETE on failure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat

EPHEMERAL_DIRS = frozenset({
    "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache"
})
REQUIRED_FILES = frozenset({
    "product-data/product_runtime/paper-events.jsonl",
    "Network/Cookies", "Local State", "Preferences",
})
JOURNAL = "product-data/product_runtime/paper-events.jsonl"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def no_reparse(path: Path) -> None:
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or
            getattr(info, "st_file_attributes", 0) &
            getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)):
        raise ValueError("REPARSE_POINT_REFUSED")


def within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def inventory(source: Path) -> list[Path]:
    records: list[Path] = []
    for current, dirs, files in os.walk(source, topdown=True, followlinks=False):
        parent = Path(current)
        no_reparse(parent)
        retained: list[str] = []
        for name in sorted(dirs):
            child = parent / name
            no_reparse(child)  # reject unexpected junctions before descending
            if name not in EPHEMERAL_DIRS:
                retained.append(name)
        dirs[:] = retained
        for name in sorted(files):
            item = parent / name
            no_reparse(item)
            rel = item.relative_to(source)
            if rel.parts == ("lockfile",):
                continue
            if any(part in EPHEMERAL_DIRS for part in rel.parts):
                continue
            records.append(rel)
    return sorted(records, key=lambda item: item.as_posix())


def snapshot(*, scratch_root: Path, source: Path, destination: Path,
             owner_profile: Path, clone_proof: Path, expected_proof_sha256: str,
             expected_source_sha: str, expected_journal_sha256: str,
             report: Path) -> dict:
    for location in (scratch_root, source, destination, owner_profile,
                     clone_proof, report):
        if not location.is_absolute():
            raise ValueError("ABSOLUTE_PATHS_REQUIRED")
    for value in (expected_source_sha, expected_journal_sha256,
                  expected_proof_sha256):
        if re.fullmatch("[a-fA-F0-9]{40}", value) is None and (
                value == expected_source_sha or
                re.fullmatch("[a-fA-F0-9]{64}", value) is None):
            raise ValueError("INVALID_EXPECTED_DIGEST")

    no_reparse(scratch_root)
    no_reparse(source)
    no_reparse(clone_proof)
    root = scratch_root.resolve(strict=True)
    src = source.resolve(strict=True)
    owner = owner_profile.resolve(strict=True)
    dst = destination.resolve(strict=False)
    output = report.resolve(strict=False)
    pending = dst.with_name(dst.name + ".INCOMPLETE")
    if (src.parent != root or dst.parent != root or output.parent != root or
            not src.name.startswith("activation-clone-") or
            dst.name != src.name + "-verified-fullsnapshot" or
            within(owner, root) or within(root, owner) or
            within(dst, src) or within(src, dst) or
            any(item.exists() or item.is_symlink()
                for item in (dst, pending, output))):
        raise ValueError("DISPOSABLE_SCRATCH_BOUNDARY_REFUSED")

    if sha256(clone_proof) != expected_proof_sha256.lower():
        raise ValueError("INDEPENDENT_CLONE_PROOF_SHA_MISMATCH")
    proof = json.loads(clone_proof.read_text(encoding="utf-8-sig"))
    if not (proof.get("decision") == "PASS_CLONE_ONLY" and
            proof.get("source_sha") == expected_source_sha.lower() and
            proof.get("owner_journal_sha256", "").lower() ==
                expected_journal_sha256.lower() and
            proof.get("owner_activated") is False and
            proof.get("original_owner_processes_preserved") is True and
            proof.get("original_owner_shortcuts_preserved") is True and
            proof.get("original_global_paper_sync_preserved") is True):
        raise ValueError("CLONE_PROOF_BOUNDARY_REFUSED")

    files = inventory(src)
    covered = {path.as_posix() for path in files}
    if not REQUIRED_FILES <= covered:
        raise ValueError("PERSISTENT_PROFILE_COVERAGE_INCOMPLETE")
    if not any(path.parts[0] == "Local Storage" for path in files):
        raise ValueError("LOCAL_STORAGE_COVERAGE_INCOMPLETE")
    if not any(path.parts[0] == "Session Storage" for path in files):
        raise ValueError("SESSION_STORAGE_COVERAGE_INCOMPLETE")
    if sha256(src / JOURNAL) != expected_journal_sha256.lower():
        raise ValueError("ORIGINAL_PAPER_JOURNAL_MISMATCH")

    baseline = {
        path: (sha256(src / path), (src / path).stat().st_size)
        for path in files
    }
    pending.mkdir(parents=False)
    copied = []
    for path in files:
        origin = src / path
        target = pending / path
        no_reparse(origin)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origin, target)  # a locked Cookies file MUST fail closed
        source_hash, size = baseline[path]
        if (sha256(origin), origin.stat().st_size) != (source_hash, size):
            raise ValueError("SOURCE_CHANGED_DURING_SNAPSHOT")
        if (sha256(target), target.stat().st_size) != (source_hash, size):
            raise ValueError("COPIED_PROFILE_DIGEST_MISMATCH")
        copied.append({"relative": path.as_posix(), "bytes": size,
                       "sha256": source_hash})
    if inventory(src) != files or any(
            (sha256(src / path), (src / path).stat().st_size) != baseline[path]
            for path in files):
        raise ValueError("SOURCE_CHANGED_AFTER_SNAPSHOT")
    if sha256(pending / JOURNAL) != expected_journal_sha256.lower():
        raise ValueError("SNAPSHOT_JOURNAL_MISMATCH")

    os.replace(pending, dst)
    evidence = {
        "schema": "nexus.disposable-electron-profile-snapshot.v1",
        "decision": "PASS_DISPOSABLE_FILE_INTEGRITY_ONLY",
        "source_sha": expected_source_sha.lower(),
        "clone_proof_sha256": expected_proof_sha256.lower(),
        "original_paper_journal_sha256": expected_journal_sha256.lower(),
        "cookies_included": True,
        "file_count": len(copied),
        "total_bytes": sum(item["bytes"] for item in copied),
        "file_manifest": copied,
        "disposable_clone_process_quiescence_independently_proven": False,
        "real_owner_full_profile_copied": False,
        "real_owner_quiescence_tested": False,
        "transactional_rollback_tested": False,
        "owner_activation_authorized": False,
    }
    with output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("scratch-root", "source", "destination", "owner-profile",
                 "clone-proof", "expected-proof-sha256", "expected-source-sha",
                 "expected-journal-sha256", "report"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    evidence = snapshot(
        scratch_root=Path(args.scratch_root),
        source=Path(args.source), destination=Path(args.destination),
        owner_profile=Path(args.owner_profile),
        clone_proof=Path(args.clone_proof),
        expected_proof_sha256=args.expected_proof_sha256,
        expected_source_sha=args.expected_source_sha,
        expected_journal_sha256=args.expected_journal_sha256,
        report=Path(args.report),
    )
    print("DISPOSABLE_PROFILE_FILE_INTEGRITY_PASS "
          f"files={evidence['file_count']} "
          "real_owner_activation=false process_quiescence_unproven=true")


if __name__ == "__main__":
    main()
