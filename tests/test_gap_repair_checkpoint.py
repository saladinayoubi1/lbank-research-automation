from __future__ import annotations

import json
from pathlib import Path

import pytest

from gap_repair_checkpoint import (
    CheckpointError,
    build_checkpoint,
    gap_set_digest,
    read_checkpoint,
    write_checkpoint,
)


def gaps():
    return [
        "2026-01-01T00:15:00+00:00",
        "2026-01-01T00:45:00+00:00",
    ]


def test_checkpoint_round_trip_survives_process_memory_loss(tmp_path: Path):
    path = tmp_path / "cursor.json"
    checkpoint = build_checkpoint(
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=gaps(),
        cursor=1,
    )
    write_checkpoint(path, checkpoint)

    restored = read_checkpoint(
        path,
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=gaps(),
    )

    assert restored.cursor == 1
    assert restored.gap_set_digest == gap_set_digest(gaps())


def test_stale_gap_set_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(
        path,
        build_checkpoint(
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
            cursor=1,
        ),
    )

    with pytest.raises(CheckpointError, match="gap-set identity"):
        read_checkpoint(
            path,
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=["2026-01-01T00:15:00+00:00"],
        )


def test_series_identity_substitution_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    write_checkpoint(
        path,
        build_checkpoint(
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
            cursor=0,
        ),
    )

    with pytest.raises(CheckpointError, match="identity"):
        read_checkpoint(
            path,
            symbol="eth_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
        )


def test_corrupt_checkpoint_is_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    path.write_text("{not-json", encoding="utf-8")

    with pytest.raises(CheckpointError, match="malformed"):
        read_checkpoint(
            path,
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
        )


def test_unknown_fields_are_rejected(tmp_path: Path):
    path = tmp_path / "cursor.json"
    checkpoint = build_checkpoint(
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=gaps(),
        cursor=0,
    )
    payload = checkpoint.__dict__ | {"authorized": True}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CheckpointError, match="schema fields"):
        read_checkpoint(
            path,
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
        )


def test_bool_and_out_of_range_cursor_are_rejected():
    with pytest.raises(CheckpointError, match="non-negative integer"):
        build_checkpoint(
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
            cursor=True,
        )

    with pytest.raises(CheckpointError, match="outside"):
        build_checkpoint(
            symbol="btc_usdt",
            timeframe="minute15",
            gap_starts=gaps(),
            cursor=2,
        )
