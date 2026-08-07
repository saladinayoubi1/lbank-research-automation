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
    (root / ".env.prod").write_text("SECRET=do-not-back-up\n", encoding="utf-8")
    (root / "private.pem").write_text("secret\n", encoding="utf-8")
    (root / "id_ed25519").write_text("secret\n", encoding="utf-8")
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
    assert not (destination / ".env.prod").exists()
    assert not (destination / "private.pem").exists()
    assert not (destination / "id_ed25519").exists()


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
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["../escape.txt"]}')
    checksum = _write_checksum(archive)

    with pytest.raises(ValueError, match="unsafe archive member"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_windows_backslash_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("..\\escape.txt", "blocked")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["..\\\\escape.txt"]}')
    checksum = _write_checksum(archive)

    with pytest.raises(ValueError, match="unsafe archive member"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_non_object_manifest(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("BACKUP_MANIFEST.json", "[]")
    checksum = _write_checksum(archive)

    with pytest.raises(ValueError, match="manifest must be an object"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_member_count_over_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("a.txt", "a")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["a.txt"]}')
    checksum = _write_checksum(archive)
    monkeypatch.setattr(backup, "MAX_MEMBER_COUNT", 1)

    with pytest.raises(ValueError, match="member count exceeds limit"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_member_size_over_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
        output.writestr("large.bin", b"12345")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["large.bin"]}')
    checksum = _write_checksum(archive)
    monkeypatch.setattr(backup, "MAX_MEMBER_BYTES", 4)

    with pytest.raises(ValueError, match="member exceeds uncompressed size limit"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_high_compression_ratio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr("bomb.txt", "A" * 10_000)
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["bomb.txt"]}')
    checksum = _write_checksum(archive)
    monkeypatch.setattr(backup, "MAX_COMPRESSION_RATIO", 2.0)

    with pytest.raises(ValueError, match="compression ratio exceeds limit"):
        backup.verify_backup(archive, checksum)


def test_verify_rejects_oversized_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 0, "files": []}')
    checksum = _write_checksum(archive)
    monkeypatch.setattr(backup, "MAX_MANIFEST_BYTES", 8)

    with pytest.raises(ValueError, match="manifest exceeds size limit"):
        backup.verify_backup(archive, checksum)


def test_restore_requires_empty_destination(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("file.txt", "safe")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["file.txt"]}')
    checksum = _write_checksum(archive)
    destination = tmp_path / "restore"
    destination.mkdir()
    (destination / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="empty directory or absent"):
        backup.restore_backup(archive, checksum, destination)
    assert (destination / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_restore_rejects_insufficient_free_space(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("file.txt", "safe")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["file.txt"]}')
    checksum = _write_checksum(archive)
    destination = tmp_path / "restore"

    class Usage:
        total = 100
        used = 99
        free = 1

    monkeypatch.setattr(backup.shutil, "disk_usage", lambda path: Usage())
    monkeypatch.setattr(backup, "MIN_FREE_SPACE_BYTES", 1)

    with pytest.raises(ValueError, match="insufficient free space"):
        backup.restore_backup(archive, checksum, destination)
    assert not destination.exists()


def test_restore_failure_does_not_publish_partial_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "backup.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("file.txt", "safe")
        output.writestr("BACKUP_MANIFEST.json", '{"file_count": 1, "files": ["file.txt"]}')
    checksum = _write_checksum(archive)
    destination = tmp_path / "restore"

    original_open = zipfile.ZipExtFile.read
    calls = {"n": 0}

    def fail_read(self, n: int = -1):
        data = original_open(self, n)
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated partial write")
        return data

    monkeypatch.setattr(zipfile.ZipExtFile, "read", fail_read)

    with pytest.raises(OSError, match="simulated partial write"):
        backup.restore_backup(archive, checksum, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".restore.restore-*"))
