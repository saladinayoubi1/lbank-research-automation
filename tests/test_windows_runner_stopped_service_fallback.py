from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUI_BOOTSTRAP = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"
RUNNER_AUTOSTART = ROOT / "scripts" / "nexus_github_runner_autostart.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_gui_bootstrap_uses_bounded_owner_fallback_only_after_service_start_failure() -> None:
    text = read(GUI_BOOTSTRAP)
    service = text.index("$service = Get-RunnerService $runner")
    wait_for_fallback = text.index("Wait-ForListener $runner", service)
    fallback = text.index("SERVICE_STOPPED_USER_FALLBACK_RUNNING", service)
    assert service < wait_for_fallback < fallback
    for marker in (
        "Start-Service",
        "Start-InteractiveRunnerFallback",
        "Get-Listener $runner",
        "System.Diagnostics.ProcessStartInfo",
        "CreateNoWindow = $true",
        "SERVICE_STOPPED_USER_FALLBACK_RUNNING",
        "SERVICE_STOPPED_USER_FALLBACK_LISTENER_NOT_OBSERVED",
        "fallback_transport = 'current_user_hidden_process'",
        "scheduled_task_changed = $false",
        "service_start_error",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "start-process" not in lowered
    assert "-verb runas" not in lowered
    assert "config.cmd" not in lowered
    assert "--token" not in lowered


def test_persistent_runner_daemon_prefers_service_but_yields_to_owner_listener_when_unstartable() -> None:
    text = read(RUNNER_AUTOSTART)
    service = text.index("$service = Get-ServiceForRunner $runner")
    running = text.index("runner_service_running", service)
    failed_start = text.index("runner_service_stopped_requires_admin", service)
    fallback = text.index("runner_service_stopped_user_fallback", failed_start)
    start_owner = text.index("Start-InteractiveRunner $runner", fallback)
    assert service < running < failed_start < fallback < start_owner
    for marker in (
        "LISTENER_RUNNING_USER_FALLBACK",
        "LISTENER_STARTING_USER_FALLBACK",
        "SERVICE_STOPPED_USER_FALLBACK_COOLDOWN",
        "Get-ListenerProcess $runner",
        "TotalSeconds -lt 60",
        "CreateNoWindow = $true",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "duplicate_runner_daemon_rejected",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "config.cmd" not in lowered
    assert "-verb runas" not in lowered
    assert "registration-token" not in lowered


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser check is Windows-only")
def test_both_runner_fallback_scripts_parse_with_windows_powershell() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    for script in (GUI_BOOTSTRAP, RUNNER_AUTOSTART):
        escaped = str(script).replace("'", "''")
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
