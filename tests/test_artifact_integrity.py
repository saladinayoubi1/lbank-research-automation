import json
from pathlib import Path

import pytest

from artifact_integrity import (
    ArtifactIntegrityError,
    build_manifest,
    load_manifest,
    verify_manifest,
    write_manifest,
)


def test_manifest_is_deterministic_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.bin").write_bytes(b"b")
    (tmp_path / "a.bin").write_bytes(b"a")

    first = build_manifest(tmp_path, [Path("b.bin"), Path("a.bin")])
    second = build_manifest(tmp_path, [Path("a.bin"), Path("b.bin")])

    assert first == second
    assert [entry["path"] for entry in first["artifacts"]] == ["a.bin", "b.bin"]


def test_create_then_verify(tmp_path: Path) -> None:
    artifact = tmp_path / "release.zip"
    artifact.write_bytes(b"release bytes")
    manifest_path = tmp_path / "manifest.json"

    write_manifest(tmp_path, [artifact], manifest_path)
    verify_manifest(tmp_path, manifest_path)


def test_tampering_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "release.zip"
    artifact.write_bytes(b"trusted")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(tmp_path, [artifact], manifest_path)

    artifact.write_bytes(b"tampered")
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        verify_manifest(tmp_path, manifest_path)


def test_missing_artifact_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "release.zip"
    artifact.write_bytes(b"trusted")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(tmp_path, [artifact], manifest_path)
    artifact.unlink()

    with pytest.raises(ArtifactIntegrityError, match="missing"):
        verify_manifest(tmp_path, manifest_path)


def test_path_escape_and_symlink_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-artifact.bin"
    outside.write_bytes(b"outside")
    with pytest.raises(ArtifactIntegrityError, match="escapes root"):
        build_manifest(tmp_path, [outside])

    target = tmp_path / "target.bin"
    target.write_bytes(b"target")
    link = tmp_path / "link.bin"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(ArtifactIntegrityError, match="non-symlink"):
        build_manifest(tmp_path, [link])


def test_malformed_manifest_and_duplicate_entries_are_rejected(tmp_path: Path) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("not-json", encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="invalid JSON"):
        load_manifest(malformed)

    artifact = tmp_path / "a.bin"
    artifact.write_bytes(b"a")
    manifest = build_manifest(tmp_path, [artifact])
    manifest["artifacts"].append(dict(manifest["artifacts"][0]))
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="duplicate"):
        verify_manifest(tmp_path, duplicate)


def test_recovery_requires_new_manifest_after_authorized_rebuild(tmp_path: Path) -> None:
    artifact = tmp_path / "release.zip"
    artifact.write_bytes(b"version-1")
    manifest_path = tmp_path / "manifest.json"
    write_manifest(tmp_path, [artifact], manifest_path)

    artifact.write_bytes(b"version-2")
    with pytest.raises(ArtifactIntegrityError):
        verify_manifest(tmp_path, manifest_path)

    write_manifest(tmp_path, [artifact], manifest_path)
    verify_manifest(tmp_path, manifest_path)
