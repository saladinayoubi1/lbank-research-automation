"""Bounded physical-to-hosted backup handoff for NEXUS Paper state."""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import shutil
import zipfile
from pathlib import Path, PurePosixPath


CHUNK_SIZE = 60_000
MAX_CHUNKS = 12
MAX_B64_BYTES = CHUNK_SIZE * MAX_CHUNKS
MAX_FILES = 20_000
MAX_EXPANDED_BYTES = 100_000_000


class PersistentStateHandoffError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_state_files(root: Path) -> list[Path]:
    files: list[Path] = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise PersistentStateHandoffError("persistent state symlink is forbidden")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise PersistentStateHandoffError("persistent state path is unsafe")
        files.append(path)
        total += path.stat().st_size
        if len(files) > MAX_FILES or total > MAX_EXPANDED_BYTES:
            raise PersistentStateHandoffError("persistent state exceeds bounded surface")
    if not files:
        raise PersistentStateHandoffError("persistent state contains no files")
    return files


def pack_state(root: str | Path, output: str | Path) -> dict[str, object]:
    source = Path(root).expanduser().resolve()
    if not source.is_dir():
        raise PersistentStateHandoffError("persistent state root is unavailable")
    files = _safe_state_files(source)
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_LZMA) as archive:
        for path in files:
            archive.write(path, path.relative_to(source).as_posix())
    encoded = base64.b64encode(target.read_bytes()).decode("ascii")
    if len(encoded) > MAX_B64_BYTES:
        raise PersistentStateHandoffError(
            "packed persistent state exceeds bounded job-output handoff"
        )
    chunks = [
        encoded[index:index + CHUNK_SIZE]
        for index in range(0, len(encoded), CHUNK_SIZE)
    ]
    if not 1 <= len(chunks) <= MAX_CHUNKS:
        raise PersistentStateHandoffError("persistent state handoff chunk count is invalid")
    return {
        "sha256": _sha256(target),
        "b64_len": len(encoded),
        "chunks": chunks,
        "zip_bytes": target.stat().st_size,
        "file_count": len(files),
    }


def write_github_outputs(result: dict[str, object], output_path: str | Path) -> None:
    chunks = list(result["chunks"])
    path = Path(output_path)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"state_archive_chunk_count={len(chunks)}\n")
        handle.write(f"state_archive_b64_len={result['b64_len']}\n")
        handle.write(f"state_archive_sha256={result['sha256']}\n")
        for index in range(MAX_CHUNKS):
            value = chunks[index] if index < len(chunks) else ""
            handle.write(f"state_archive_chunk_{index}={value}\n")


def _validate_archive(path: Path) -> None:
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_FILES:
                raise PersistentStateHandoffError("state handoff ZIP file count is invalid")
            for member in members:
                pure = PurePosixPath(member.filename)
                if (
                    pure.is_absolute()
                    or not pure.parts
                    or any(part in {"", ".", ".."} for part in pure.parts)
                ):
                    raise PersistentStateHandoffError(
                        f"unsafe state handoff path: {member.filename}"
                    )
                mode = (member.external_attr >> 16) & 0o170000
                if mode == 0o120000:
                    raise PersistentStateHandoffError("state handoff symlink is forbidden")
                total += member.file_size
                if total > MAX_EXPANDED_BYTES:
                    raise PersistentStateHandoffError(
                        "state handoff expanded size exceeds bound"
                    )
    except zipfile.BadZipFile as exc:
        raise PersistentStateHandoffError("state handoff is not a valid ZIP") from exc


def rehydrate_from_environment(output: str | Path) -> dict[str, object]:
    try:
        count = int(os.environ["STATE_ARCHIVE_CHUNK_COUNT"])
        expected_len = int(os.environ["STATE_ARCHIVE_B64_LEN"])
        expected_sha = os.environ["STATE_ARCHIVE_SHA256"].strip().lower()
    except (KeyError, ValueError) as exc:
        raise PersistentStateHandoffError("state handoff metadata is unavailable") from exc
    if not 1 <= count <= MAX_CHUNKS or not 0 < expected_len <= MAX_B64_BYTES:
        raise PersistentStateHandoffError("state handoff metadata exceeds bounds")
    chunks: list[str] = []
    for index in range(MAX_CHUNKS):
        value = os.environ.get(f"STATE_ARCHIVE_CHUNK_{index}", "")
        if len(value) > CHUNK_SIZE:
            raise PersistentStateHandoffError("state handoff chunk exceeds bound")
        if index < count:
            if not value:
                raise PersistentStateHandoffError("required state handoff chunk is empty")
            chunks.append(value)
        elif value:
            raise PersistentStateHandoffError("unexpected trailing state handoff chunk")
    encoded = "".join(chunks)
    if len(encoded) != expected_len:
        raise PersistentStateHandoffError("state handoff base64 length mismatch")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise PersistentStateHandoffError("state handoff base64 is invalid") from exc
    target = Path(output).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    actual_sha = _sha256(target)
    if actual_sha != expected_sha:
        target.unlink(missing_ok=True)
        raise PersistentStateHandoffError("state handoff SHA-256 mismatch")
    _validate_archive(target)
    return {"sha256": actual_sha, "zip_bytes": len(raw), "chunk_count": count}


def extract_validated(archive_path: str | Path, destination: str | Path) -> None:
    archive = Path(archive_path).resolve()
    _validate_archive(archive)
    target = Path(destination).resolve()
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    pack = sub.add_parser("pack")
    pack.add_argument("--state-root", type=Path, required=True)
    pack.add_argument("--output", type=Path, required=True)
    pack.add_argument("--github-output", type=Path)
    rehydrate = sub.add_parser("rehydrate")
    rehydrate.add_argument("--output", type=Path, required=True)
    rehydrate.add_argument("--extract-root", type=Path)
    args = parser.parse_args()
    if args.command == "pack":
        result = pack_state(args.state_root, args.output)
        if args.github_output is not None:
            write_github_outputs(result, args.github_output)
        print(
            f"persistent_state_handoff_pack=PASS files={result['file_count']} "
            f"zip_bytes={result['zip_bytes']} chunks={len(result['chunks'])}"
        )
        return 0
    result = rehydrate_from_environment(args.output)
    if args.extract_root is not None:
        extract_validated(args.output, args.extract_root)
    print(
        f"persistent_state_handoff_rehydrate=PASS zip_bytes={result['zip_bytes']} "
        f"chunks={result['chunk_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
