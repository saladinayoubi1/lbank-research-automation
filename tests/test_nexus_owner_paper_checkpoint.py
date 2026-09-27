"""Stage-only checkpoint validation; never accesses a real owner profile or runner."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import random
import tarfile

import pytest

from scripts.nexus_owner_paper_checkpoint import (
    CheckpointError, _load, commit, restore, validate_archive,
)

SOURCE = "a" * 40
OTHER = "b" * 40


def archive(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz", preset=6) as tar:
        for name, payload in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mode = 0o600
            info.mtime = 0
            tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def stage(tmp_path: Path, payload: bytes) -> Path:
    path = tmp_path / "incoming.tar.xz"
    path.write_bytes(payload)
    return path


def sample(files: int = 1) -> dict[str, bytes]:
    return {
        f"paper/entry-{i:04d}.jsonl": b'{"paper_only":true,"live_trading_authority":false,"balance":500}\n'
        for i in range(files)
    }


def test_stage_commit_verify_and_restore_independent_destination(tmp_path):
    contents = sample(1636)
    packed = archive(contents)
    assert len(contents) == 1636
    root = tmp_path / "private-checkpoints"
    info = commit(root, stage(tmp_path, packed), "36311000000", SOURCE)
    assert info["source_sha"] == SOURCE
    assert info["previous_run_id"] is None
    restored = tmp_path / "isolated-restore"
    assert restore(root, restored) == info
    for name in ("paper/entry-0000.jsonl", "paper/entry-1635.jsonl"):
        assert (restored / name).read_bytes() == contents[name]
    assert (root / "objects" / (info["archive_sha256"] + ".tar.xz")).read_bytes() == packed
    assert _load(root)[0] == info


def test_newer_commit_preserves_immutable_history_and_idempotence(tmp_path):
    root = tmp_path / "root"
    first = archive(sample())
    second = archive({"paper/entry.jsonl": b'{"paper_only":true,"balance":499.75}\n'})
    start = commit(root, stage(tmp_path, first), "36311000000", SOURCE)
    assert commit(root, stage(tmp_path, first), "36311000000", SOURCE) == start
    latest = commit(root, stage(tmp_path, second), "36311000001", OTHER)
    assert latest["previous_run_id"] == start["run_id"]
    assert (root / "objects" / (start["archive_sha256"] + ".tar.xz")).read_bytes() == first
    assert (root / "commits" / (start["run_id"] + ".json")).is_file()
    restored = tmp_path / "restore"
    restore(root, restored)
    assert (restored / "paper/entry.jsonl").read_bytes() == b'{"paper_only":true,"balance":499.75}\n'
    with pytest.raises(CheckpointError, match="older run"):
        commit(root, stage(tmp_path, first), "36311000000", SOURCE)
    assert _load(root)[0] == latest


def test_same_run_conflict_and_failed_attempt_never_replace_latest(tmp_path):
    root = tmp_path / "root"
    first = archive(sample())
    original = commit(root, stage(tmp_path, first), "36311000000", SOURCE)
    pointer = (root / "latest.json").read_bytes()
    conflict = archive({"paper/other": b"changed"})
    with pytest.raises(CheckpointError, match="same-run"):
        commit(root, stage(tmp_path, conflict), "36311000000", SOURCE)
    assert (root / "latest.json").read_bytes() == pointer
    assert _load(root)[0] == original


def test_tampered_archive_and_manifest_fail_closed_without_fallback(tmp_path):
    for target in ("archive", "manifest", "pointer"):
        root = tmp_path / target
        first = archive(sample())
        info = commit(root, stage(tmp_path, first), "36311000000", SOURCE)
        if target == "archive":
            (root / "objects" / (info["archive_sha256"] + ".tar.xz")).write_bytes(b"corrupt")
        elif target == "manifest":
            (root / "commits" / "36311000000.json").write_text("{}")
        else:
            (root / "latest.json").write_text('{"run_id":"36311000000","manifest_sha256":"bad"}')
        with pytest.raises(CheckpointError):
            restore(root, tmp_path / ("restore-" + target))
        with pytest.raises(CheckpointError):
            commit(root, stage(tmp_path, first), "36311000001", SOURCE)
        assert not (tmp_path / ("restore-" + target)).exists()


def test_restore_never_overwrites_existing_owner_data(tmp_path):
    root = tmp_path / "root"
    commit(root, stage(tmp_path, archive(sample())), "36311000000", SOURCE)
    dest = tmp_path / "owner-journal"
    dest.mkdir()
    sentinel = dest / "KEEP"
    sentinel.write_text("do not touch")
    with pytest.raises(CheckpointError, match="must not exist"):
        restore(root, dest)
    assert sentinel.read_text() == "do not touch"


@pytest.mark.parametrize("name", (
    "../../escape.jsonl", "/absolute.jsonl", "paper/../escape.jsonl",
    "paper//entry.jsonl", "paper\\entry.jsonl",
))
def test_reject_archive_traversal_and_noncanonical_names(name):
    with pytest.raises(CheckpointError, match="unsafe"):
        validate_archive(archive({name: b"unsafe"}))


def test_reject_casefold_duplicates_and_link_members():
    packed = archive({"Paper/ENTRY": b"one", "paper/entry": b"two"})
    with pytest.raises(CheckpointError, match="duplicate"):
        validate_archive(packed)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        link = tarfile.TarInfo("paper/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../outside"
        tar.addfile(link)
    with pytest.raises(CheckpointError, match="unsafe"):
        validate_archive(buf.getvalue())


def test_reject_corrupted_xz_empty_and_oversized_payload(tmp_path):
    with pytest.raises(CheckpointError):
        validate_archive(b"x" * 10)
    with pytest.raises(CheckpointError, match="no files"):
        validate_archive(archive({}))
    with pytest.raises(CheckpointError, match="outside bounds"):
        validate_archive(b"x" * 800_001)
    oversized = archive({"paper/large.bin": bytes(random.Random(19).randbytes(1_200_000))})
    assert len(oversized) > 800_000
    with pytest.raises(CheckpointError, match="outside bounds"):
        commit(tmp_path / "root", stage(tmp_path, oversized), "36311000000", SOURCE)


def test_pointer_is_immutable_chain_and_large_realistic_archive(tmp_path):
    root = tmp_path / "checkpoint"
    a = archive({"paper/large.bin": random.Random(18).randbytes(410_000)})
    assert 400_000 < len(a) < 800_000
    first = commit(root, stage(tmp_path, a), "36311000000", SOURCE)
    b = archive(sample(1636))
    second = commit(root, stage(tmp_path, b), "36311000001", SOURCE)
    assert second["previous_run_id"] == first["run_id"]
    assert second["previous_manifest_sha256"] == hashlib.sha256((root / "commits" / "36311000000.json").read_bytes()).hexdigest()
    assert (root / "objects" / (first["archive_sha256"] + ".tar.xz")).exists()


def test_missing_checkpoint_never_makes_up_state(tmp_path):
    with pytest.raises(CheckpointError):
        restore(tmp_path / "missing", tmp_path / "isolated-restore")
    assert not (tmp_path / "isolated-restore").exists()
