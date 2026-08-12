from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import gap_repair_checkpoint as checkpoint_module
from gap_repair_checkpoint import (
    CheckpointError,
    build_checkpoint,
    checkpoint_lock,
    gap_set_digest,
    initialized_marker,
    lock_path,
    read_checkpoint,
    write_checkpoint,
)


def gaps():
    return ["2026-01-01T00:15:00+00:00", "2026-01-01T00:45:00+00:00"]


def test_checkpoint_round_trip_survives_process_memory_loss(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(path, build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1))
    restored = read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())
    assert restored.cursor == 1
    assert restored.gap_set_digest == gap_set_digest(gaps())
    assert initialized_marker(path).exists()


def test_deleted_initialized_checkpoint_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(path, build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1))
    path.unlink()
    with pytest.raises(CheckpointError, match="missing after prior initialization"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())


def test_concurrent_checkpoint_owner_fails_closed(tmp_path: Path):
    path = tmp_path / "cursor.json"
    with checkpoint_lock(path):
        assert lock_path(path).exists()
        with pytest.raises(CheckpointError, match="ownership is locked"):
            with checkpoint_lock(path):
                pass
    assert not lock_path(path).exists()


def test_preexisting_orphan_lock_is_not_broken_automatically(tmp_path: Path):
    path = tmp_path / "cursor.json"
    lock = lock_path(path)
    lock.write_text("999999", encoding="ascii")

    with pytest.raises(CheckpointError, match="ownership is locked"):
        with checkpoint_lock(path):
            pass

    assert lock.exists()
    assert lock.read_text(encoding="ascii") == "999999"


def test_stale_gap_set_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(path, build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1))
    with pytest.raises(CheckpointError, match="gap-set identity"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=["2026-01-01T00:15:00+00:00"])


def test_reordered_gap_sequence_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    original = gaps()
    write_checkpoint(path, build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=original, cursor=1))
    with pytest.raises(CheckpointError, match="gap-set identity"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=list(reversed(original)))
    assert gap_set_digest(original) != gap_set_digest(list(reversed(original)))


def test_series_identity_substitution_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(path, build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=0))
    with pytest.raises(CheckpointError, match="identity"):
        read_checkpoint(path, symbol="eth_usdt", timeframe="minute15", gap_starts=gaps())


def test_corrupt_checkpoint_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(CheckpointError, match="malformed"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())


def test_unknown_fields_are_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    checkpoint = build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=0)
    path.write_text(json.dumps(checkpoint.__dict__ | {"authorized": True}), encoding="utf-8")
    with pytest.raises(CheckpointError, match="schema fields"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())


def test_unsupported_schema_downgrade_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    checkpoint = build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=0)
    payload = checkpoint.__dict__ | {"schema_version": 0}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CheckpointError, match="schema version is unsupported"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())


def test_bool_and_out_of_range_cursor_are_rejected():
    with pytest.raises(CheckpointError, match="non-negative integer"):
        build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=True)
    with pytest.raises(CheckpointError, match="outside"):
        build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=2)


def test_checkpoint_symlink_substitution_is_rejected(tmp_path: Path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")
    target = tmp_path / "outside.json"
    checkpoint = build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1)
    target.write_text(json.dumps(checkpoint.__dict__), encoding="utf-8")
    path = tmp_path / "cursor.json"
    try:
        path.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    with pytest.raises(CheckpointError, match="path substitution"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())
    with pytest.raises(CheckpointError, match="path substitution"):
        write_checkpoint(path, checkpoint)
    with pytest.raises(CheckpointError, match="path substitution"):
        with checkpoint_lock(path):
            pass


def test_checkpoint_marker_symlink_substitution_is_rejected(tmp_path: Path):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")
    path = tmp_path / "cursor.json"
    target = tmp_path / "outside.marker"
    target.write_text("", encoding="utf-8")
    marker = initialized_marker(path)
    try:
        marker.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    checkpoint = build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1)
    with pytest.raises(CheckpointError, match="marker path substitution"):
        write_checkpoint(path, checkpoint)
    with pytest.raises(CheckpointError, match="marker path substitution"):
        read_checkpoint(path, symbol="btc_usdt", timeframe="minute15", gap_starts=gaps())


def test_checkpoint_write_syncs_directory_entry_mutations(monkeypatch, tmp_path: Path):
    path = tmp_path / "cursor.json"
    synced = []
    monkeypatch.setattr(checkpoint_module, "_fsync_parent_directory", lambda value: synced.append(value))

    write_checkpoint(
        path,
        build_checkpoint(symbol="btc_usdt", timeframe="minute15", gap_starts=gaps(), cursor=1),
    )

    assert path in synced
    assert initialized_marker(path) in synced


def test_checkpoint_lock_syncs_create_and_remove(monkeypatch, tmp_path: Path):
    path = tmp_path / "cursor.json"
    synced = []
    monkeypatch.setattr(checkpoint_module, "_fsync_parent_directory", lambda value: synced.append(value))

    with checkpoint_lock(path):
        assert lock_path(path).exists()

    assert synced == [lock_path(path), lock_path(path)]
