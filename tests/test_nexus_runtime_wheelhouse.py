from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.nexus_runtime_wheelhouse import deterministic_pack, safe_extract_flat_archive


def test_deterministic_pack_is_stable_and_flat(tmp_path: Path) -> None:
    root = tmp_path / "wheelhouse"
    root.mkdir()
    (root / "requirements.lock").write_text("demo==1.0\n", encoding="utf-8")
    (root / "demo-1.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_digest = deterministic_pack(root, first)
    second_digest = deterministic_pack(root, second)

    assert first.read_bytes() == second.read_bytes()
    assert first_digest == second_digest == hashlib.sha256(first.read_bytes()).hexdigest()
    with zipfile.ZipFile(first) as archive:
        assert archive.namelist() == ["demo-1.0-py3-none-any.whl", "requirements.lock"]


def test_safe_extract_rejects_path_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.whl", b"bad")

    with pytest.raises(RuntimeError, match="unsafe archive path"):
        safe_extract_flat_archive(archive_path, tmp_path / "out")


def test_safe_extract_rejects_unexpected_wheelhouse_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-member.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("payload.txt", b"bad")

    with pytest.raises(RuntimeError, match="unexpected wheelhouse member"):
        safe_extract_flat_archive(archive_path, tmp_path / "out")
