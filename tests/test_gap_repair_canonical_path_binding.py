from __future__ import annotations

from pathlib import Path

import pytest

from gap_repair_checkpoint import (
    CheckpointError,
    build_checkpoint,
    checkpoint_lock,
    lock_path,
    read_checkpoint,
    write_checkpoint,
)


def gaps() -> list[str]:
    return ["2026-01-01T00:15:00+00:00", "2026-01-01T00:45:00+00:00"]


def lexical_alias(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.parent / "alias-component" / ".." / path.name


def test_lexical_alias_reads_same_checkpoint_identity(tmp_path: Path) -> None:
    canonical = tmp_path / "state" / "cursor.json"
    alias = lexical_alias(canonical)
    checkpoint = build_checkpoint(
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=gaps(),
        cursor=1,
    )

    write_checkpoint(alias, checkpoint)

    restored = read_checkpoint(
        canonical,
        symbol="btc_usdt",
        timeframe="minute15",
        gap_starts=gaps(),
    )
    assert restored.cursor == 1
    assert canonical.exists()
    assert not (canonical.parent / "alias-component").exists()


def test_lexical_alias_cannot_create_second_lock_domain(tmp_path: Path) -> None:
    canonical = tmp_path / "state" / "cursor.json"
    alias = lexical_alias(canonical)

    with checkpoint_lock(canonical):
        with pytest.raises(CheckpointError, match="active in another process"):
            with checkpoint_lock(alias):
                pass

    assert lock_path(canonical).exists()
