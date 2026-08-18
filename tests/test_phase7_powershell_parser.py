from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = [
    ROOT / "scripts" / "phase7_offline_laptop.ps1",
    ROOT / "scripts" / "nexus_windows_autostart.ps1",
    ROOT / "scripts" / "nexus_github_runner_autostart.ps1",
]


@pytest.mark.skipif(os.name != "nt", reason="PowerShell parser proof requires Windows")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_windows_helpers_parse_with_windows_powershell(script: Path):
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell, "Windows PowerShell is required on windows-latest"
    assert script.is_file()

    env = os.environ.copy()
    env["NEXUS_WINDOWS_PS1"] = str(script)
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:NEXUS_WINDOWS_PS1,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }; "
        "Write-Output 'nexus_windows_powershell_parse_valid=true'"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "nexus_windows_powershell_parse_valid=true" in completed.stdout
