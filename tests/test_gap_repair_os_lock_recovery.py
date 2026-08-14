from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import time

import pytest

from gap_repair_checkpoint import CheckpointError, checkpoint_lock


def _python(code: str, *args: str) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    return subprocess.Popen(
        [sys.executable, "-c", code, *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def test_live_owner_blocks_second_process(tmp_path: Path):
    checkpoint = tmp_path / "cursor.json"
    holder = _python(
        textwrap.dedent(
            """
            import sys, time
            from pathlib import Path
            from gap_repair_checkpoint import checkpoint_lock
            with checkpoint_lock(Path(sys.argv[1])):
                print('LOCKED', flush=True)
                time.sleep(30)
            """
        ),
        str(checkpoint),
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "LOCKED"
        with pytest.raises(CheckpointError, match="active in another process"):
            with checkpoint_lock(checkpoint):
                pass
    finally:
        holder.terminate()
        holder.wait(timeout=10)


def test_abrupt_process_exit_releases_kernel_lock_without_lockfile_deletion(tmp_path: Path):
    checkpoint = tmp_path / "cursor.json"
    holder = _python(
        textwrap.dedent(
            """
            import os, sys
            from pathlib import Path
            from gap_repair_checkpoint import checkpoint_lock
            with checkpoint_lock(Path(sys.argv[1])):
                print('LOCKED', flush=True)
                os._exit(17)
            """
        ),
        str(checkpoint),
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "LOCKED"
    holder.wait(timeout=10)
    assert holder.returncode == 17

    lockfile = Path(f"{checkpoint}.lock")
    assert lockfile.exists()

    # The stale coordination inode remains, but ownership itself died with the
    # crashed process. A clean process can acquire immediately without PID/age
    # guessing or deleting another process's lock path.
    with checkpoint_lock(checkpoint):
        assert lockfile.exists()
