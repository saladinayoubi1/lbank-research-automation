"""Exercise the real headless main-process bridge in the normal test suite."""
import shutil
import subprocess
from pathlib import Path

import pytest


def test_chatgpt_main_process_boundary():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is absent; Windows package build runs the mandatory bridge suite")
    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run([node, "--test", str(root / "tests/test_product_chatgpt_bridge.cjs")],
                               cwd=root, capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
