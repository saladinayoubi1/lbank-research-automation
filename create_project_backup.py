"""Create a compact, restorable project archive without caches or secrets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP_ROOT = ROOT / "backups"
EXCLUDED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "backups"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".tmp", ".log"}
EXCLUDED_NAMES = {".env", "credentials.json", "token.json"}


def should_include(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in relative.parts):
        return False
    if path.name in EXCLUDED_NAMES or path.suffix.lower() in EXCLUDED_SUFFIXES:
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
        output.writestr("BACKUP_MANIFEST.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    checksum_path = archive.with_suffix(".sha256")
    checksum_path.write_text(f"{sha256(archive)}  {archive.name}\n", encoding="utf-8")
    return archive, checksum_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label")
    args = parser.parse_args()
    archive, checksum = create_backup(args.label)
    print(f"Backup: {archive}")
    print(f"Checksum: {checksum}")
    print("Upload these two files to Google Drive / LBANK_PROJECT_ARCHIVE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
