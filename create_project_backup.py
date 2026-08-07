"""Create, verify, and safely restore compact project backups."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
BACKUP_ROOT = ROOT / "backups"
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "backups"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log", ".pem", ".key", ".p12", ".pfx"}
EXCLUDED_NAMES = {".env", "credentials.json", "token.json", "secrets.json"}
MANIFEST_NAME = "BACKUP_MANIFEST.json"

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_COUNT = 10_000
MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_COMPRESSION_RATIO = 200.0
MAX_PATH_LENGTH = 512
MAX_PATH_DEPTH = 32
MIN_FREE_SPACE_BYTES = 64 * 1024 * 1024
ALLOWED_COMPRESSION_METHODS = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}


def _looks_secret(path: Path) -> bool:
    name = path.name.lower()
    return (
        name in EXCLUDED_NAMES
        or name.startswith(".env.")
        or path.suffix.lower() in EXCLUDED_SUFFIXES
        or name.startswith("id_rsa")
        or name.startswith("id_ed25519")
    )


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if _looks_secret(path):
        return False
    return path.is_file()


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_backup(label: str | None = None) -> tuple[Path, Path]:
    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_label = "" if not label else "-" + "".join(ch for ch in label if ch.isalnum() or ch in "-_")[:40]
    archive = BACKUP_ROOT / f"lbank-project-{stamp}{safe_label}.zip"

    included: list[str] = []
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for path in sorted(ROOT.rglob("*")):
            if should_include(path):
                relative = path.relative_to(ROOT).as_posix()
                output.write(path, relative)
                included.append(relative)

        manifest = {
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "project_root": str(ROOT),
            "git_branch": git_value("branch", "--show-current"),
            "git_commit": git_value("rev-parse", "HEAD"),
            "file_count": len(included),
            "excluded_directories": sorted(EXCLUDED_DIRS),
            "excluded_secret_names": sorted(EXCLUDED_NAMES),
            "files": included,
        }
        output.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    checksum_path = archive.with_suffix(".sha256")
    checksum_path.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, checksum_path


def _safe_member_name(name: str) -> str:
    if not name or "\\" in name or "\x00" in name or len(name) > MAX_PATH_LENGTH:
        raise ValueError(f"unsafe archive member: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or any(part in {"", "."} for part in path.parts):
        raise ValueError(f"unsafe archive member: {name!r}")
    if len(path.parts) > MAX_PATH_DEPTH:
        raise ValueError(f"unsafe archive member: {name!r}")
    return path.as_posix()


def _validate_member_budget(members: list[zipfile.ZipInfo]) -> None:
    if len(members) > MAX_MEMBER_COUNT:
        raise ValueError("backup member count exceeds limit")
    total_uncompressed = 0
    for member in members:
        if member.compress_type not in ALLOWED_COMPRESSION_METHODS:
            raise ValueError("unsupported ZIP compression method")
        if member.file_size < 0 or member.compress_size < 0:
            raise ValueError("invalid ZIP member size")
        if member.file_size > MAX_MEMBER_BYTES:
            raise ValueError("backup member exceeds uncompressed size limit")
        total_uncompressed += member.file_size
        if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("backup uncompressed size exceeds limit")
        if member.file_size and member.compress_size == 0:
            raise ValueError("backup member compression ratio exceeds limit")
        if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
            raise ValueError("backup member compression ratio exceeds limit")


def verify_backup(archive: Path, checksum_path: Path) -> dict[str, object]:
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("backup archive must be a regular non-symlink file")
    if archive.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("backup archive exceeds size limit")

    expected_line = checksum_path.read_text(encoding="utf-8").strip().split()
    if len(expected_line) != 2 or expected_line[1] != archive.name:
        raise ValueError("invalid checksum file format or archive name")
    expected_digest = expected_line[0].lower()
    if len(expected_digest) != 64 or any(ch not in "0123456789abcdef" for ch in expected_digest):
        raise ValueError("invalid checksum digest")
    if sha256(archive) != expected_digest:
        raise ValueError("backup checksum mismatch")

    with zipfile.ZipFile(archive, "r") as source:
        members = source.infolist()
        _validate_member_budget(members)
        names = [member.filename for member in members]
        if len(names) != len(set(names)):
            raise ValueError("duplicate archive member")
        safe_names = [_safe_member_name(name) for name in names]
        if any(member.is_dir() for member in members):
            raise ValueError("directory archive members are not supported")
        if MANIFEST_NAME not in safe_names:
            raise ValueError("backup manifest missing")
        manifest_member = members[safe_names.index(MANIFEST_NAME)]
        if manifest_member.file_size > MAX_MANIFEST_BYTES:
            raise ValueError("backup manifest exceeds size limit")
        bad_member = source.testzip()
        if bad_member is not None:
            raise ValueError(f"corrupt archive member: {bad_member}")
        try:
            manifest = json.loads(source.read(MANIFEST_NAME).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("invalid backup manifest") from exc

    if not isinstance(manifest, dict):
        raise ValueError("backup manifest must be an object")
    files = manifest.get("files")
    if not isinstance(files, list) or any(not isinstance(item, str) for item in files):
        raise ValueError("backup manifest files must be a string list")
    safe_manifest_files = [_safe_member_name(item) for item in files]
    if len(files) != manifest.get("file_count"):
        raise ValueError("backup manifest file_count mismatch")
    if len(safe_manifest_files) != len(set(safe_manifest_files)):
        raise ValueError("backup manifest contains duplicate files")
    if set(safe_manifest_files) != set(safe_names) - {MANIFEST_NAME}:
        raise ValueError("backup manifest does not match archive contents")
    return manifest


def restore_backup(archive: Path, checksum_path: Path, destination: Path) -> dict[str, object]:
    manifest = verify_backup(archive, checksum_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("restore destination must be an empty directory or absent")

    required_bytes = sum(
        member.file_size
        for member in zipfile.ZipFile(archive, "r").infolist()
        if member.filename != MANIFEST_NAME
    )
    if shutil.disk_usage(destination.parent).free < required_bytes + MIN_FREE_SPACE_BYTES:
        raise ValueError("insufficient free space for bounded restore")

    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.restore-", dir=destination.parent))
    written_total = 0
    try:
        with zipfile.ZipFile(archive, "r") as source:
            for member in source.infolist():
                name = _safe_member_name(member.filename)
                if name == MANIFEST_NAME:
                    continue
                target = staging / Path(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                member_written = 0
                with source.open(member, "r") as src, target.open("xb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        member_written += len(chunk)
                        written_total += len(chunk)
                        if member_written > MAX_MEMBER_BYTES or written_total > MAX_TOTAL_UNCOMPRESSED_BYTES:
                            raise ValueError("restore output exceeds byte budget")
                        dst.write(chunk)
                if member_written != member.file_size:
                    raise ValueError("restored member size mismatch")

        if destination.exists():
            destination.rmdir()
        os.replace(staging, destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")

    create_parser = subparsers.add_parser("create")
    create_parser.add_argument("--label")

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("archive", type=Path)
    verify_parser.add_argument("checksum", type=Path)

    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("archive", type=Path)
    restore_parser.add_argument("checksum", type=Path)
    restore_parser.add_argument("destination", type=Path)

    args = parser.parse_args()
    command = args.command or "create"
    if command == "create":
        archive, checksum = create_backup(getattr(args, "label", None))
        print(f"Backup: {archive}")
        print(f"Checksum: {checksum}")
        print("Upload these two files to Google Drive / LBANK_PROJECT_ARCHIVE.")
        return 0
    if command == "verify":
        verify_backup(args.archive, args.checksum)
        print("Backup verification: valid (integrity only; not source authenticity)")
        return 0
    if command == "restore":
        restore_backup(args.archive, args.checksum, args.destination)
        print(f"Restore verification: valid -> {args.destination}")
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
