"""The default CI suite exercises OAuth/IPC without owner credentials or internet."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_tradingview_main_process_boundary():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node absent; Windows package CI runs the mandatory bridge suite")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, "--test", str(root / "tests/test_product_tradingview_bridge.cjs")],
                            cwd=root, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
