from pathlib import Path
import shutil
import subprocess

import pytest


def test_provider_ui_routing_identity_and_freshness_errors():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the browser-script behavior check")
    script = Path(__file__).resolve().parents[1] / "scripts/test_product_research_data_ui.js"
    result = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
