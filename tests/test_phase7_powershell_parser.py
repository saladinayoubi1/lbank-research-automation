from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase7_offline_laptop.ps1"


@pytest.mark.skipif(os.name != "nt", reason="PowerShell parser proof requires Windows")
def test_phase7_offline_helper_parses_with_windows_powershell():
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell, "Windows PowerShell is required on windows-latest"
    assert SCRIPT.is_file()

    env = os.environ.copy()
    env["NEXUS_PHASE7_PS1"] = str(SCRIPT)
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:NEXUS_PHASE7_PS1,[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }; "
        "Write-Output 'phase7_powershell_parse_valid=true'"
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
    assert "phase7_powershell_parse_valid=true" in completed.stdout
