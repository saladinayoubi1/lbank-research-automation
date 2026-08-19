from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
ENTRY = DESKTOP / "bootstrap-main.js"
SCRIPT = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"


def test_bootstrap_entrypoint_parses_with_node_when_available() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available on this CI image")
    completed = subprocess.run(
        [node, "--check", str(ENTRY)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_bootstrap_powershell_parses_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parser check is Windows-only")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped_script = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped_script}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count -gt 0){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_windows_package_stages_bootstrap_before_electron_builder() -> None:
    package = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
    dist = package["scripts"]["dist:win"]
    assert "copyFileSync('../../scripts/bootstrap_nexus_runner_from_gui.ps1'" in dist
    assert "sidecar/bootstrap_nexus_runner_from_gui.ps1" in dist
    assert dist.index("copyFileSync") < dist.index("electron-builder")
