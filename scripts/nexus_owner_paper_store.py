#!/usr/bin/env python3
"""Fail-closed, owner-volume-only persistent Paper checkpoint store.

Runs on the owner WSL Linux runner. GitHub holds CI/watchdog receipts, not the
runtime database. Never run this against the owner's installed Windows journal.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import uuid

SCHEMA = "nexus.owner-paper-checkpoint.v1"
SHA = re.compile(r"[a-f0-9]{64}\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
RUN = re.compile(r"[0-9]{1,24}\Z")
MAX_ARCHIVE = 32_000_000
MAX_UNCOMPRESSED = 100_000_000
MAX_FILES = 10_000
STATE_TOP = frozenset({
    "persistent-loop-state.json", "matrix-state.json", "cells", "demo",
    "regime_runtime_drift", "regime_runtime_evidence", "regime_selected",
})
# Explicitly exclude GitHub source-download metadata, including signed URLs.
PREP_TOP = frozenset({
    "source-run-metadata.json", "source-artifact-metadata.json",
    "source-artifact-redirect.headers", "source-artifact.zip",
    "nexus-persistent-paper-exact-source.zip",
    "nexus-persistent-paper-exact-source.commit-sha",
})


class StoreError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise StoreError(message)


def no_symlinks(path: Path) -> None:
    require(not any(p.is_symlink() for p in (path, *path.parents)), "symlink in protected path")


def regular(path: Path) -> None:
    no_symlinks(path)
    require(stat.S_ISREG(path.lstat().st_mode), "non-regular protected file")


def digest(path: Path) -> str:
    regular(path)
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            result.update(block)
    return result.hexdigest()


def write_atomic(path: Path, data: bytes) -> None:
    target = path.parent
    no_symlinks(target)
    temp = target / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temp.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        require(not path.is_symlink(), "attempted symlink pointer overwrite")
        os.replace(temp, path)
        # DrvFS may reject directory fsync; NTFS atomic same-volume rename
        # plus a flushed file is the supported baseline for this owner volume.
        try:
            fd = os.open(target, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError as exc:
            if exc.errno not in (errno.EINVAL, errno.ENOTSUP, errno.EBADF, errno.EACCES):
                raise
    finally:
        temp.unlink(missing_ok=True)


def canonical(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def load_json(path: Path, limit: int = 8192) -> dict:
    regular(path)
    require(0 < path.stat().st_size <= limit, "oversized or empty protected manifest")
    value = json.loads(path.read_text(encoding="ascii"))
    require(isinstance(value, dict), "invalid protected manifest")
    return value


@contextlib.contextmanager
def locked(root: Path):
    no_symlinks(root)
    root.mkdir(parents=True, exist_ok=True)
    no_symlinks(root)
    lock = root / ".owner-paper.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def validate_receipt(root: Path, receipt: dict) -> Path:
    require(receipt.get("schema") == SCHEMA, "unknown checkpoint schema")
    run = str(receipt.get("run_id", ""))
    source = receipt.get("source_sha")
    checksum = receipt.get("archive_sha256")
    previous = receipt.get("previous_archive_sha256")
    require(bool(RUN.fullmatch(run)), "invalid checkpoint run id")
    require(isinstance(source, str) and bool(COMMIT.fullmatch(source)), "invalid checkpoint source")
    require(isinstance(checksum, str) and bool(SHA.fullmatch(checksum)), "invalid checkpoint digest")
    require(previous is None or (isinstance(previous, str) and bool(SHA.fullmatch(previous))),
            "invalid checkpoint predecessor")
    require(isinstance(receipt.get("archive_bytes"), int) and
            0 < receipt["archive_bytes"] <= MAX_ARCHIVE, "invalid checkpoint byte count")
    require(isinstance(receipt.get("file_count"), int) and
            1 <= receipt["file_count"] <= MAX_FILES, "invalid checkpoint file count")
    require(isinstance(receipt.get("uncompressed_bytes"), int) and
            0 < receipt["uncompressed_bytes"] <= MAX_UNCOMPRESSED, "invalid checkpoint state bytes")
    name = f"{run}-{checksum[:16]}"
    require(receipt.get("generation") == name, "checkpoint generation mismatch")
    base = root / "snapshots" / name
    no_symlinks(base)
    stored = load_json(base / "receipt.json")
    require(canonical(stored) == canonical(receipt), "checkpoint pointer/receipt mismatch")
    archive = base / "paper-state.tar.xz"
    require(archive.stat().st_size == receipt["archive_bytes"], "checkpoint archive size changed")
    require(digest(archive) == checksum, "checkpoint SHA256 mismatch")
    return archive


def current(root: Path) -> dict | None:
    pointer = root / "current.json"
    if not pointer.exists() and not pointer.is_symlink():
        snapshots = root / "snapshots"
        require(not snapshots.exists() or
                (snapshots.is_dir() and not snapshots.is_symlink() and not any(snapshots.iterdir())),
                "orphaned owner snapshots without pointer: require manual recovery")
        return None
    value = load_json(pointer)
    validate_receipt(root, value)
    return value


def authority(state: Path) -> None:
    snapshot = state / "demo" / "persistent-paper-trading-loop.json"
    regular(snapshot)
    data = load_json(snapshot, 10_000_000)
    require(data.get("paper_only") is True and
            data.get("live_trading_authority") is False and
            data.get("private_credentials_used") is False and
            data.get("real_exchange_orders") is False and
            data.get("automatic_strategy_promotion") is False and
            data.get("state_isolated_from_issue_984") is True,
            "Paper-only authority check failed")


def state_files(state: Path) -> list[Path]:
    no_symlinks(state)
    require(state.is_dir(), "missing isolated Paper state")
    unexpected = {p.name for p in state.iterdir()} - STATE_TOP - PREP_TOP
    require(not unexpected, "unknown Paper state surface: refusing lossy checkpoint")
    result = []
    for name in sorted(STATE_TOP):
        item = state / name
        if not item.exists() and not item.is_symlink():
            continue
        no_symlinks(item)
        if item.is_dir():
            for child in sorted(item.rglob("*")):
                no_symlinks(child)
                if child.is_file():
                    regular(child)
                    result.append(child)
                else:
                    require(child.is_dir(), "unexpected Paper state entry")
        else:
            regular(item)
            result.append(item)
    require(bool(result), "empty Paper state")
    return result


def pack(state: Path, target: Path) -> tuple[int, int]:
    authority(state)
    files = state_files(state)
    total = 0
    with tarfile.open(target, "w:xz", preset=6) as archive:
        for path in files:
            size = path.stat().st_size
            total += size
            require(len(files) <= MAX_FILES and total <= MAX_UNCOMPRESSED,
                    "Paper state exceeds fixed bounds")
            relative = path.relative_to(state).as_posix()
            info = archive.gettarinfo(str(path), arcname=relative)
            require(info.isfile(), "Paper state changed during pack")
            info.uid = info.gid = info.mtime = 0
            info.uname = info.gname = ""
            info.mode = 0o600
            with path.open("rb") as handle:
                archive.addfile(info, handle)
    require(0 < target.stat().st_size <= MAX_ARCHIVE, "checkpoint archive exceeds bound")
    return len(files), total


def restore_archive(archive: Path, receipt: dict, state: Path) -> None:
    no_symlinks(state)
    require(state.is_dir() and not any(state.iterdir()), "restore target must be empty")
    staged = state / f".verified-restore-{uuid.uuid4().hex}"
    staged.mkdir()
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(archive, "r:xz") as source:
            for member in source:
                pure = PurePosixPath(member.name)
                require(member.isfile() and not member.issym() and not member.islnk(),
                        "unsafe checkpoint entry type")
                require(not pure.is_absolute() and bool(pure.parts) and
                        all(part not in ("", ".", "..") for part in pure.parts) and
                        "\\" not in member.name and pure.parts[0] in STATE_TOP,
                        "unsafe checkpoint path")
                require(member.name not in seen, "duplicate checkpoint path")
                seen.add(member.name)
                total += member.size
                require(len(seen) <= MAX_FILES and total <= MAX_UNCOMPRESSED,
                        "checkpoint decompression bound exceeded")
                dest = staged.joinpath(*pure.parts)
                dest.parent.mkdir(parents=True, exist_ok=True)
                incoming = source.extractfile(member)
                require(incoming is not None, "unreadable checkpoint entry")
                with incoming, dest.open("xb") as out:
                    shutil.copyfileobj(incoming, out, length=1 << 20)
        require(len(seen) == receipt["file_count"] and
                total == receipt["uncompressed_bytes"], "checkpoint state counts differ")
        authority(staged)
        for name in sorted(STATE_TOP):
            if (staged / name).exists():
                os.replace(staged / name, state / name)
    finally:
        shutil.rmtree(staged, ignore_errors=True)


def owner_volume(store: Path) -> None:
    # A separate Windows E: volume prevents filling the Linux root filesystem.
    anchor = Path("/mnt/e/NEXUS")
    no_symlinks(store)
    require(store == anchor or anchor in store.parents, "owner store must reside under /mnt/e/NEXUS")
    mounts = Path("/proc/mounts").read_text(encoding="utf-8").splitlines()
    require(any(row.split()[1:3] == ["/mnt/e", "drvfs"] for row in mounts if len(row.split()) >= 3),
            "verified Windows E drive is not mounted in WSL")
    statvfs = os.statvfs("/mnt/e")
    require(statvfs.f_bavail * statvfs.f_frsize >= 2_000_000_000,
            "insufficient free space on owner Windows E drive")


def cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("volume-check", "status", "restore", "commit"))
    parser.add_argument("--store-root", type=Path, required=True)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--source-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--expected-previous", default="none")
    parser.add_argument("--github-env-file", type=Path)
    parser.add_argument("--require-owner-volume", action="store_true")
    args = parser.parse_args()
    root = args.store_root.absolute()
    if args.require_owner_volume or args.operation == "volume-check":
        owner_volume(root)
    if args.operation == "volume-check":
        print("OWNER_VOLUME_READY")
        return 0
    with locked(root):
        old = current(root)
        if args.operation == "status":
            print("OWNER_STORE_EMPTY" if old is None else
                  f"OWNER_STORE_VALIDATED archive_sha256={old['archive_sha256']} run_id={old['run_id']}")
            return 0
        require(args.state_root is not None, "isolated Paper state path required")
        state = args.state_root.absolute()
        no_symlinks(state)
        require(root != state and root not in state.parents and state not in root.parents,
                "checkpoint and work state must be disjoint")
        if args.operation == "restore":
            if old is None:
                print("OWNER_STORE_EMPTY")
                return 3  # Only this exact code permits legacy artifact bootstrap.
            state.mkdir(parents=True, exist_ok=True)
            archive = validate_receipt(root, old)
            restore_archive(archive, old, state)
            if args.github_env_file:
                with args.github_env_file.open("a", encoding="ascii") as output:
                    output.write(f"NEXUS_OWNER_PREVIOUS_ARCHIVE_SHA={old['archive_sha256']}\n")
            print(f"OWNER_RESTORE_VERIFIED run_id={old['run_id']} sha256={old['archive_sha256']}")
            return 0
        require(bool(args.source_sha and COMMIT.fullmatch(args.source_sha)),
                "source_sha must be exact Git commit")
        require(bool(args.run_id and RUN.fullmatch(args.run_id)), "numeric run ID required")
        previous = None if old is None else old["archive_sha256"]
        require(args.expected_previous == (previous or "none"),
                "owner checkpoint advanced concurrently; reject stale commit")
        root.joinpath("snapshots").mkdir(exist_ok=True)
        staged = root / f".staged-{args.run_id}-{uuid.uuid4().hex}"
        staged.mkdir()
        try:
            archive = staged / "paper-state.tar.xz"
            count, total = pack(state, archive)
            checksum = digest(archive)
            generation = f"{args.run_id}-{checksum[:16]}"
            receipt = {
                "schema": SCHEMA, "generation": generation,
                "source_sha": args.source_sha, "run_id": args.run_id,
                "archive_sha256": checksum, "previous_archive_sha256": previous,
                "archive_bytes": archive.stat().st_size,
                "file_count": count, "uncompressed_bytes": total,
                "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            write_atomic(staged / "receipt.json", canonical(receipt))
            dest = root / "snapshots" / generation
            require(not dest.exists() and not dest.is_symlink(), "checkpoint generation already exists")
            os.rename(staged, dest)  # Never replace any prior generation.
            validate_receipt(root, receipt)
            write_atomic(root / "current.json", canonical(receipt))
            validate_receipt(root, load_json(root / "current.json"))
            if args.github_env_file:
                with args.github_env_file.open("a", encoding="ascii") as output:
                    output.write(f"NEXUS_OWNER_ARCHIVE_SHA={checksum}\n")
                    output.write(f"NEXUS_OWNER_CHECKPOINT_RUN_ID={args.run_id}\n")
            print(f"OWNER_COMMIT_VERIFIED archive_sha256={checksum} run_id={args.run_id}")
            return 0
        finally:
            if staged.exists():
                shutil.rmtree(staged)


if __name__ == "__main__":
    try:
        sys.exit(cli())
    except (StoreError, OSError, ValueError, json.JSONDecodeError, tarfile.TarError) as exc:
        print("OWNER_STORE_FAIL_CLOSED: " + str(exc), file=sys.stderr)
        sys.exit(1)
