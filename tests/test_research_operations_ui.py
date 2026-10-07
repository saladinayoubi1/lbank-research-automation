"""Exercise the actual shipped UI JavaScript without a browser or fake status API."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_research_operations_ui_contract_and_escape_regression() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js unavailable; static same-origin web checks still run")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "scripts" / "test_nexus_research_operations_ui.js")],
        cwd=root, text=True, capture_output=True, timeout=25, check=False,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
    assert "PASS" in result.stdout


def test_periodic_mission_refresh_keeps_professional_agent_dashboard() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "product_ui" / "product-mission.js").read_text(encoding="utf-8")
    assert "if (!host || $('missionAgentRuntime') || window.NexusResearchOps) return;" in script
    assert "window.NexusResearchOps.render(m,{onRefresh:refreshMission})" in script
    assert "window.NexusResearchOps.render({reason:err.message})" in script
