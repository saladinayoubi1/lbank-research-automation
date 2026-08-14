from __future__ import annotations

import os
from pathlib import Path

import pytest

import gap_repair_checkpoint as checkpoint_module


def test_durable_replace_persists_replacement_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source.tmp"
    destination = tmp_path / "destination.json"
    source.write_bytes(b"new-checkpoint\n")
    destination.write_bytes(b"old-checkpoint\n")

    checkpoint_module._replace_durable(source, destination)

    assert not source.exists()
    assert destination.read_bytes() == b"new-checkpoint\n"


@pytest.mark.skipif(os.name != "nt", reason="Windows write-through replacement contract")
def test_windows_durable_replace_uses_real_filesystem_path(tmp_path: Path) -> None:
    source = tmp_path / "windows-source.tmp"
    destination = tmp_path / "windows-destination.json"
    source.write_bytes(b"windows-durable\n")

    checkpoint_module._replace_durable(source, destination)

    assert destination.read_bytes() == b"windows-durable\n"
    with destination.open("r+b") as handle:
        os.fsync(handle.fileno())
