from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"


def read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_gui_runner_bootstrap_does_not_depend_on_cim_or_scheduledtasks_cmdlets() -> None:
    text = read()
    lowered = text.casefold()
    for forbidden in (
        "get-ciminstance",
        "new-scheduledtaskaction",
        "new-scheduledtasktrigger",
        "new-scheduledtaskprincipal",
        "new-scheduledtasksettingsset",
        "new-scheduledtask ",
        "register-scheduledtask",
        "start-scheduledtask",
    ):
        assert forbidden not in lowered


def test_gui_runner_bootstrap_has_cim_independent_process_service_and_task_transports() -> None:
    text = read()
    for marker in (
        "System.Diagnostics.Process]::GetProcessesByName('Runner.Listener')",
        "Registry::HKEY_LOCAL_MACHINE\\SYSTEM\\CurrentControlSet\\Services",
        "Get-Service -Name $name",
        "Schedule.Service",
        "RegisterTaskDefinition",
        "Principal.LogonType = 3",
        "Principal.RunLevel = 0",
        "Triggers.Create(9)",
        "task_scheduler_transport = 'COM'",
    ):
        assert marker in text


def test_gui_runner_bootstrap_preserves_non_registration_safety_boundary() -> None:
    text = read()
    for marker in (
        "runner_registered = $false",
        "config_cmd_invoked = $false",
        "credentials_modified = $false",
        "live_trading_authority = $false",
        "paper_only = $true",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "registration-token" not in lowered
    assert "config.cmd --unattended" not in lowered
    assert "set-executionpolicy" not in lowered
    assert "runas" not in lowered


def test_gui_runner_bootstrap_powershell_parses_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parser check is Windows-only")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
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
