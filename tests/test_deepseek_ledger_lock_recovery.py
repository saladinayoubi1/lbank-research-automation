import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

import deepseek_provider as ds


def _child_code(lock_path: Path, ready_path: Path, mode: str) -> str:
    return (
        "from pathlib import Path\n"
        "import os, time\n"
        "import deepseek_provider as ds\n"
        f"lock = Path({str(lock_path)!r})\n"
        f"ready = Path({str(ready_path)!r})\n"
        "ctx = ds._ledger_lock(lock, timeout=2.0)\n"
        "ctx.__enter__()\n"
        "ready.write_text('ready', encoding='utf-8')\n"
        + ("os._exit(0)\n" if mode == "crash" else "time.sleep(3.0)\nctx.__exit__(None, None, None)\n")
    )


def _wait_ready(path: Path, proc: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if path.exists():
            return
        if proc.poll() is not None:
            raise AssertionError(f"lock holder exited early with {proc.returncode}")
        time.sleep(0.02)
    raise AssertionError("lock holder did not become ready")


def test_live_owner_blocks_contender(tmp_path):
    lock_path = tmp_path / "usage.json"
    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, "-c", _child_code(lock_path, ready, "hold")], text=True)
    try:
        _wait_ready(ready, proc)
        with pytest.raises(ds.DeepSeekError, match="locked or recovery"):
            with ds._ledger_lock(lock_path, timeout=0.15):
                pass
    finally:
        proc.terminate()
        proc.wait(timeout=3)


def test_abrupt_process_exit_releases_kernel_lock(tmp_path):
    lock_path = tmp_path / "usage.json"
    ready = tmp_path / "ready"
    proc = subprocess.Popen([sys.executable, "-c", _child_code(lock_path, ready, "crash")], text=True)
    _wait_ready(ready, proc)
    assert proc.wait(timeout=3) == 0

    # The persistent coordination file may remain, but process ownership must not.
    assert lock_path.with_suffix(lock_path.suffix + ".lock").exists()
    with ds._ledger_lock(lock_path, timeout=0.5):
        pass
