"""Fail-closed stage-only owner-controlled Paper checkpoint primitives.

This module does NOT schedule a trading loop, access an exchange, or change the
existing persistent Paper workflow. A future separately reviewed integration
must prove owner volume, filesystem semantics, retention and independent restore.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import lzma
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import tarfile
import tempfile

SCHEMA = "nexus.owner-paper-checkpoint.v1"
MAX_COMPRESSED = 800_000
MAX_UNCOMPRESSED = 100_000_000
MAX_FILES = 10_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[1-9][0-9]{0,19}\Z")


class CheckpointError(ValueError):
    """State checkpoint is missing, inconsistent or unsafe."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(data: dict) -> bytes:
    return (json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _no_symlink_ancestors(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink():
            raise CheckpointError("checkpoint path traverses a symbolic link")


def _directory(path: Path) -> None:
    _no_symlink_ancestors(path)
    path.mkdir(parents=True, exist_ok=True)
    _no_symlink_ancestors(path)
    if not path.is_dir():
        raise CheckpointError("checkpoint path is not a directory")


def _atomic(path: Path, data: bytes) -> None:
    _directory(path.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".pending-", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _read_regular(path: Path, limit: int) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise CheckpointError("checkpoint file is missing or unsafe")
    if not 0 < path.stat().st_size <= limit:
        raise CheckpointError("checkpoint file size is outside bounds")
    return path.read_bytes()


def validate_archive(raw: bytes) -> tuple[int, int]:
    if not 0 < len(raw) <= MAX_COMPRESSED:
        raise CheckpointError("compressed Paper archive is outside bounds")
    count = total = 0
    names: set[str] = set()
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
            for member in archive:
                name = member.name
                parts = name.split("/")
                normalized = PurePosixPath(name)
                if (not member.isfile() or not parts or
                        any(p in {"", ".", ".."} for p in parts) or
                        "\\" in name or normalized.is_absolute()):
                    raise CheckpointError("unsafe Paper archive member")
                casefold = normalized.as_posix().casefold()
                if casefold in names:
                    raise CheckpointError("duplicate Paper archive member")
                names.add(casefold)
                count += 1
                total += member.size
                if count > MAX_FILES or total > MAX_UNCOMPRESSED:
                    raise CheckpointError("Paper archive exceeds safety bounds")
                stream = archive.extractfile(member)
                if stream is None:
                    raise CheckpointError("unreadable Paper archive member")
                read = 0
                with stream:
                    while block := stream.read(1024 * 1024):
                        read += len(block)
                        if read > member.size:
                            raise CheckpointError("Paper member exceeds stated size")
                if read != member.size:
                    raise CheckpointError("truncated Paper archive member")
    except (tarfile.TarError, EOFError, OSError, lzma.LZMAError) as exc:
        raise CheckpointError("invalid or truncated Paper archive") from exc
    if not count:
        raise CheckpointError("Paper archive has no files")
    return count, total


def _load(root: Path) -> tuple[dict, bytes]:
    _no_symlink_ancestors(root)
    pointer = json.loads(_read_regular(root / "latest.json", 2048))
    if set(pointer) != {"run_id", "manifest_sha256"}:
        raise CheckpointError("checkpoint latest pointer has unknown fields")
    run_id, manifest_sha = pointer["run_id"], pointer["manifest_sha256"]
    if not isinstance(run_id, str) or not _RUN.fullmatch(run_id):
        raise CheckpointError("invalid checkpoint run identity")
    if not isinstance(manifest_sha, str) or not _SHA.fullmatch(manifest_sha):
        raise CheckpointError("invalid checkpoint manifest digest")
    manifest_bytes = _read_regular(root / "commits" / f"{run_id}.json", 4096)
    if _sha(manifest_bytes) != manifest_sha:
        raise CheckpointError("checkpoint manifest digest mismatch")
    manifest = json.loads(manifest_bytes)
    expected = {"schema", "run_id", "source_sha", "archive_sha256", "archive_bytes",
                "previous_run_id", "previous_manifest_sha256"}
    if set(manifest) != expected or manifest["schema"] != SCHEMA or manifest["run_id"] != run_id:
        raise CheckpointError("invalid checkpoint manifest schema")
    if not isinstance(manifest["source_sha"], str) or not _SOURCE.fullmatch(manifest["source_sha"]):
        raise CheckpointError("invalid checkpoint source identity")
    archive_sha = manifest["archive_sha256"]
    if not isinstance(archive_sha, str) or not _SHA.fullmatch(archive_sha):
        raise CheckpointError("invalid checkpoint archive digest")
    if not isinstance(manifest["archive_bytes"], int) or not 0 < manifest["archive_bytes"] <= MAX_COMPRESSED:
        raise CheckpointError("invalid checkpoint archive size")
    raw = _read_regular(root / "objects" / f"{archive_sha}.tar.xz", MAX_COMPRESSED)
    if _sha(raw) != archive_sha or len(raw) != manifest["archive_bytes"]:
        raise CheckpointError("checkpoint archive digest or size mismatch")
    validate_archive(raw)
    return manifest, raw


def commit(root: Path, archive_path: Path, run_id: str, source_sha: str) -> dict:
    """Append an immutable archive before atomically switching latest.json."""
    if not _RUN.fullmatch(run_id) or not _SOURCE.fullmatch(source_sha):
        raise CheckpointError("invalid current-run identity")
    root = Path(root)
    _directory(root)
    raw = _read_regular(Path(archive_path), MAX_COMPRESSED)
    validate_archive(raw)
    sha = _sha(raw)
    prior = prior_sha = None
    if (root / "latest.json").exists() or (root / "latest.json").is_symlink():
        previous, previous_raw = _load(root)
        if int(run_id) < int(previous["run_id"]):
            raise CheckpointError("older run cannot replace the newest checkpoint")
        if run_id == previous["run_id"]:
            if previous["source_sha"] != source_sha or previous_raw != raw:
                raise CheckpointError("same-run checkpoint conflicts with immutable history")
            return previous
        prior = previous["run_id"]
        prior_sha = _sha(_read_regular(root / "commits" / f"{prior}.json", 4096))
    object_path = root / "objects" / f"{sha}.tar.xz"
    if object_path.exists() or object_path.is_symlink():
        if _read_regular(object_path, MAX_COMPRESSED) != raw:
            raise CheckpointError("immutable archive object conflicts with digest")
    else:
        _atomic(object_path, raw)
    metadata = {"schema": SCHEMA, "run_id": run_id, "source_sha": source_sha,
                "archive_sha256": sha, "archive_bytes": len(raw),
                "previous_run_id": prior, "previous_manifest_sha256": prior_sha}
    manifest_path = root / "commits" / f"{run_id}.json"
    manifest = _json(metadata)
    if manifest_path.exists() or manifest_path.is_symlink():
        if _read_regular(manifest_path, 4096) != manifest:
            raise CheckpointError("same-run immutable manifest already differs")
    else:
        _atomic(manifest_path, manifest)
    _atomic(root / "latest.json", _json({"run_id": run_id, "manifest_sha256": _sha(manifest)}))
    verified, verified_raw = _load(root)
    if verified != metadata or verified_raw != raw:
        raise CheckpointError("checkpoint post-commit verification failed")
    return verified


def restore(root: Path, destination: Path) -> dict:
    """Restore only into a nonexistent isolated target; never overwrite owner data."""
    root, destination = Path(root), Path(destination)
    metadata, raw = _load(root)
    _no_symlink_ancestors(destination)
    if destination.exists() or destination.is_symlink():
        raise CheckpointError("restore destination must not exist")
    _directory(destination.parent)
    staging = Path(tempfile.mkdtemp(prefix=".paper-restore-", dir=destination.parent))
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:xz") as archive:
            for member in archive:
                # Archive was fully scanned and content-checked by _load.
                target = staging.joinpath(*PurePosixPath(member.name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                stream = archive.extractfile(member)
                if stream is None:
                    raise CheckpointError("unreadable Paper restore member")
                with stream, target.open("xb") as out:
                    shutil.copyfileobj(stream, out, 1024 * 1024)
                    out.flush()
                    os.fsync(out.fileno())
        if destination.exists() or destination.is_symlink():
            raise CheckpointError("restore target appeared during extraction")
        os.replace(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return metadata


def main() -> None:
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="command", required=True)
    add = sub.add_parser("commit")
    add.add_argument("--root", type=Path, required=True)
    add.add_argument("--archive", type=Path, required=True)
    add.add_argument("--run-id", required=True)
    add.add_argument("--source-sha", required=True)
    read = sub.add_parser("verify")
    read.add_argument("--root", type=Path, required=True)
    back = sub.add_parser("restore")
    back.add_argument("--root", type=Path, required=True)
    back.add_argument("--destination", type=Path, required=True)
    args = cli.parse_args()
    if args.command == "commit":
        result = commit(args.root, args.archive, args.run_id, args.source_sha)
    elif args.command == "verify":
        result, _ = _load(args.root)
    else:
        result = restore(args.root, args.destination)
    # No journal rows, credentials, archive payload, or untrusted exception text.
    print(json.dumps({"schema": result["schema"], "run_id": result["run_id"],
                      "source_sha": result["source_sha"], "archive_sha256": result["archive_sha256"]},
                     sort_keys=True))


if __name__ == "__main__":
    main()
