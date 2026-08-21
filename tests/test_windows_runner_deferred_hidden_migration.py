from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFER = ROOT / "scripts" / "defer_nexus_runner_hidden_migration.ps1"
REPAIR_CMD = ROOT / "FIX_NEXUS_RUNNER_WINDOW.cmd"


def test_deferred_migration_does_not_interrupt_active_github_job() -> None:
    text = DEFER.read_text(encoding="utf-8")
    for marker in (
        "WAITING_FOR_ACTIVE_JOB",
        "TIMEOUT_WAITING_FOR_ACTIVE_JOB",
        "active_job_interrupted = $false",
        "Get-Process -Name 'Runner.Worker'",
        "Invoke-HiddenRepair",
        "retrying_without_interrupt=true",
        "NEXUS-Runner-Hidden-Migration",
        "runner_registration_modified = $false",
        "credentials_modified = $false",
        "paper_only = $true",
        "live_trading_authority = $false",
    ):
        assert marker in text

    worker_wait = text.index("$worker = Get-ManagedWorker")
    repair_attempt = text.index("$exitCode = Invoke-HiddenRepair")
    assert worker_wait < repair_attempt


def test_deferred_migration_is_hidden_and_bounded() -> None:
    text = DEFER.read_text(encoding="utf-8")
    for marker in (
        "CreateNoWindow = $true",
        "ProcessWindowStyle]::Hidden",
        "TimeoutMinutes = 75",
        "TimeoutMinutes -gt 180",
        "PollSeconds -gt 60",
        "HiddenRepairScript",
        "-Mode Install",
    ):
        assert marker in text
    assert "Stop-Process -Name Runner.Worker" not in text
    assert "taskkill" not in text.casefold()


def test_one_click_window_repair_returns_immediately_and_defers_work() -> None:
    cmd = REPAIR_CMD.read_text(encoding="utf-8")
    assert "defer_nexus_runner_hidden_migration.ps1" in cmd
    assert "CreateNoWindow=$true" in cmd
    assert "Active GitHub jobs will not be interrupted" in cmd
    assert "install_nexus_runner_hidden_autostart.ps1" not in cmd
    assert "WaitForExit" not in cmd


def test_deferred_migration_powershell_parses_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parser check is Windows-only")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped = str(DEFER).replace("'", "''")
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
