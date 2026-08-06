from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

import create_project_backup as backup


def _write_checksum(archive: Path) -> Path:
    checksum = archive.with_suffix(".sha256")
    checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n", encoding="utf-8")
    return checksum


def test_backup_round_trip_and_secret_exclusion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    root.mkdir()
    (root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=do-not-back-up\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "data.json").write_text('{"ok": true}\n', encoding="utf-8")

    monkeypatch.setattr(backup, "ROOT", root)
    monkeypatch.setattr(backup, "BACKUP_ROOT", root / "backups")
    monkeypatch.setattr(backup, "git_value", lambda *args: "test")

    archive, checksum = backup.create_backup("roundtrip")
    manifest = backup.verify_backup(archive, checksum)
    assert sorted(manifest["files"]) == ["app.py", "nested/data.json"]

    destination = tmp_path / "restore"
    backup.restore_backup(archive, checksum, destination)
    assert (destination / "app.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert (destination / "nested" / "data.json").read_text(encoding="utf-8") == '{"ok": true}\n'
    assert not (destination / ".env").exists()


def test_verify_rejects_checksum_mismatch(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 0, "files": []}')
    checksum = archive.with_suffix(".sha256")
    checksum.write_text(f"{'0' * 64}  {archive.name}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_path_traversal_before_restore(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "blocked")
        output.writestr(
            "BACKUP_MANIFEST.json",
            '{"file_count": 1, "files": ["../escape.txt"]}',
        )
    checksum = _write_checksum(archive)

    with pytest.raises(ValueError, match="unsafe archive member"):
        backup.verify_backup(archive, checksum)


def test_restore_requires_empty_destination(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("file.txt", "safe")
        output.writestr(
            "BACKUP_MANIFEST.json",
            '{"file_count": 1, "files": ["file.txt"]}',
        )
    checksum = _write_checksum(archive)
    destination = tmp_path / "restore"
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="must be empty"):
        backup.restore_backup(archive, checksum, destination)
    assert (destination / "existing.txt").read_text(encoding="utf-8") == "keep"
