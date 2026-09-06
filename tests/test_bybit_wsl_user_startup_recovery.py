import os
from pathlib import Path
import subprocess


SCRIPT = Path("scripts/install_nexus_bybit_wsl_user_startup.ps1")


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_recovery_is_user_context_and_non_admin() -> None:
    text = _text()
    assert "S-1-5-18" in text
    assert "S-1-5-19" in text
    assert "S-1-5-20" in text
    assert "UserInteractive" in text
    assert "administrator_required = $false" in text
    assert "task_scheduler_used = $false" in text
    assert "schtasks" not in text.lower()
    assert "Schedule.Service" not in text


def test_recovery_preserves_existing_runner_registration() -> None:
    text = _text()
    assert "'/opt/nexus-bybit-runner'" in text
    assert "'NEXUS-BYBIT-WSL'" in text
    assert "test -x '$RunnerRoot/run.sh'" in text
    assert "test -f '$RunnerRoot/.runner'" in text
    assert "runner_registration_modified = $false" in text
    assert "runner_credentials_modified = $false" in text
    for forbidden in ("config.sh", "--token", "registration-token", "remove.sh"):
        assert forbidden not in text


def test_recovery_uses_per_user_startup_and_managed_child_watchdog() -> None:
    text = _text()
    assert "GetFolderPath('Startup')" in text
    assert "BybitWSLUserStartup" in text
    assert "-Mode Watch" in text
    assert "Start-Sleep -Seconds 15" in text
    assert "Local\\NEXUS-Bybit-WSL-Watchdog-v" in text
    assert "$watchdogGeneration = 5" in text
    assert "Start-ManagedRunnerProcess" in text
    assert "exec ./run.sh" in text
    assert "RUNNER_ALLOW_RUNASROOT=1" in text
    assert "RUNNER_TRACKING_ID=" in text
    assert "watchdog_owns_wsl_child = $true" in text
    assert "watchdog_owns_wsl_child=true" in text
    assert "nohup ./run.sh" not in text


def test_wsl_probe_interop_is_timeout_bounded() -> None:
    text = _text()
    assert "$wslTimeoutMilliseconds = 10000" in text
    assert "WaitForExit($wslTimeoutMilliseconds)" in text
    assert "exit_code = 124" in text
    assert "wsl_timeout" in text
    assert "runner_process_probe_timeout=true" in text
    assert "watchdog_generation = $watchdogGeneration" in text
    assert "wsl_call_timeout_seconds" in text
    assert "$psi.RedirectStandardInput = $true" in text
    assert "$Process.StandardInput.Write($Command)" in text
    assert "$Process.StandardInput.Close()" in text
    assert "base64 -d" not in text
    assert "-u root -- bash'" in text


def test_watchdog_recycles_only_idle_external_listener() -> None:
    text = _text()
    assert "Stop-IdleExternalListener" in text
    assert "Runner.Worker" in text
    assert "exit 3" in text
    assert "active_worker_interrupt_allowed = $false" in text
    assert "active_worker_interrupt_allowed=false" in text
    assert "stale_idle_listener_recycle = $true" in text
    assert "stale_idle_listener_recycle=true" in text
    assert "existing_runner_worker_active_waiting=true" in text


def test_managed_child_is_liveness_probed_without_interrupting_worker_or_unknown_state() -> None:
    text = _text()
    assert "$managedChildMissingListenerThreshold = 3" in text
    assert "managed_child_liveness_probe = $true" in text
    assert "managed_child_liveness_probe=true" in text
    assert "missing_listener_recycle_after_probes" in text
    assert "$managedState = Get-RunnerProcessState" in text
    assert "managed_child_state_unknown_no_interrupt=true" in text
    assert "managed_child_worker_active_no_interrupt=true" in text
    assert "managed_child_missing_listener_probe=" in text
    assert "managed_child_stale_recycle=true" in text
    assert "unknown_probe_interrupt_allowed = $false" in text
    assert "unknown_probe_interrupt_allowed=false" in text
    worker_guard = text.split("elseif ($managedState.worker)", 1)[1].split(
        "elseif ($managedState.listener)", 1
    )[0]
    assert "$managedRunner.Kill()" not in worker_guard
    unknown_guard = text.split("if (-not $managedState.known)", 1)[1].split(
        "elseif ($managedState.worker)", 1
    )[0]
    assert "$managedRunner.Kill()" not in unknown_guard


def test_upgrade_cleans_only_prior_same_user_watchdog_process() -> None:
    text = _text()
    assert "Stop-PreviousUserWatchdogs" in text
    assert "System.Management.ManagementObjectSearcher" in text
    assert "Win32_Process WHERE Name='powershell.exe'" in text
    assert "IndexOf($stableScript" in text
    assert "-Mode\\s+Watch" in text
    assert "previous_watchdog_terminated_pid=" in text
    assert "Stop-Process" not in text


def test_recovery_startup_launcher_is_fully_hidden() -> None:
    text = _text()
    assert "NEXUS-Bybit-WSL-User-Startup.vbs" in text
    assert 'CreateObject("WScript.Shell")' in text
    assert 'shell.Run "' in text
    assert '", 0, False' in text
    assert "popup_launcher_used = $false" in text
    assert "NEXUS-Bybit-WSL-User-Startup.cmd" in text
    assert "Remove-Item -LiteralPath $legacyStartupCmd -Force" in text


def test_recovery_does_not_expand_trading_or_windows_authority() -> None:
    text = _text()
    assert "windows_acl_modified = $false" in text
    assert "windows_service_modified = $false" in text
    assert "private_exchange_credentials_used = $false" in text
    assert "live_trading_authority_changed = $false" in text
    for forbidden in ("icacls", "sc.exe", "New-Service", "Set-Acl", "api_key", "api_secret"):
        assert forbidden.lower() not in text.lower()


def test_recovery_script_parses_on_windows_powershell() -> None:
    if os.name != "nt":
        return
    command = (
        "$errors=$null;"
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT.as_posix()}',[ref]$null,[ref]$errors) | Out-Null;"
        "if($errors.Count -ne 0){$errors | ForEach-Object { Write-Error $_ }; exit 1}"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
    )
