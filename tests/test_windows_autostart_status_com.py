"""Read-only, CIM-independent status verification for owner autostart daemons."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    ROOT / "scripts" / "nexus_windows_autostart.ps1",
    ROOT / "scripts" / "nexus_github_runner_autostart.ps1",
)


@pytest.mark.parametrize("script", SCRIPTS)
def test_status_uses_existing_read_only_com_snapshot(script: Path) -> None:
    code = script.read_text(encoding="utf-8-sig")
    status = code.split("function Show-Status {", 1)[1].split("function Run-Daemon {", 1)[0]
    assert "nexus_task_scheduler_compat.ps1" in status
    assert "Get-NexusScheduledTaskSnapshot $TaskName" in status
    assert "LastTaskResult:" in status
    assert "RunLevel:" in status
    assert "Get-ScheduledTask " not in status
    assert "Get-ScheduledTaskInfo" not in status
    assert "Register-ScheduledTask" not in status
    assert "New-NexusInteractiveLogonTask" not in status
    assert "Start-NexusScheduledTask" not in status
    assert "Remove-NexusScheduledTask" not in status
    assert "throw 'Task Scheduler COM compatibility helper is missing.'" in status


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser only")
@pytest.mark.parametrize("script", SCRIPTS)
def test_cim_independent_status_scripts_parse_in_windows_powershell(script: Path) -> None:
    ps = shutil.which("powershell.exe")
    if not ps:
        pytest.skip("Windows PowerShell unavailable")
    escaped = str(script).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count -gt 0){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
    )
    result = subprocess.run(
        [ps, "-NoProfile", "-NonInteractive", "-Command", command],
        text=True, capture_output=True, timeout=25, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
