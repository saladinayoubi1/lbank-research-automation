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


def test_gui_bootstrap_uses_bounded_owner_fallback_after_service_start_failure() -> None:
    text = read(GUI_BOOTSTRAP)
    service = text.index("$service = Get-RunnerService $runner")
    start_failure = text.index("if ($serviceStartError)", service)
    start_owner = text.index("Start-InteractiveRunnerFallback $runner 'service_start_denied'", start_failure)
    fallback = text.index("SERVICE_STOPPED_USER_FALLBACK_RUNNING", start_owner)
    assert service < start_failure < start_owner < fallback
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


def test_gui_bootstrap_does_not_treat_running_service_as_healthy_without_listener() -> None:
    text = read(GUI_BOOTSTRAP)
    service = text.index("$service = Get-RunnerService $runner")
    was_running = text.index("$serviceWasRunning = ([string]$service.State -eq 'Running')", service)
    bounded_wait = text.index("Wait-ForListener $runner 8", was_running)
    stale_guard = text.index("if (-not $listener -and $serviceWasRunning)", bounded_wait)
    start_owner = text.index("Start-InteractiveRunnerFallback $runner 'service_running_listener_absent'", stale_guard)
    success = text.index("SERVICE_RUNNING_STALE_USER_FALLBACK_RUNNING", start_owner)
    assert service < was_running < bounded_wait < stale_guard < start_owner < success
    for marker in (
        "SERVICE_RUNNING_STALE_USER_FALLBACK_RUNNING",
        "SERVICE_RUNNING_STALE_USER_FALLBACK_LISTENER_NOT_OBSERVED",
        "service_was_running = $true",
        "fallback_transport = 'current_user_hidden_process'",
        "scheduled_task_changed = $false",
    ):
        assert marker in text
    # Start-InteractiveRunnerFallback performs one final Get-Listener check before
    # launching run.cmd, which bounds the duplicate-listener race.
    helper = text[text.index("function Start-InteractiveRunnerFallback"):text.index("function Install-InteractiveRunnerTask")]
    assert "$existing = Get-Listener $Runner" in helper
    assert "if ($existing) { return [int]$existing.ProcessId }" in helper
    lowered = text.casefold()
    assert "stop-service" not in lowered
    assert "restart-service" not in lowered
    assert "config.cmd" not in lowered
    assert "--token" not in lowered
    assert "-verb runas" not in lowered


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
