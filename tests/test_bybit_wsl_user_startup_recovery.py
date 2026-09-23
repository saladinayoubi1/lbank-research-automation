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
    assert "test -x '__RUNNER_ROOT__/run.sh'" in text
    assert "test -f '__RUNNER_ROOT__/.runner'" in text
    assert "while IFS= read -r line; do" in text
    assert "grep -E" not in text
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
    assert "$Generation = 9" in text
    assert "$watchdogGeneration = $Generation" in text
    assert "Start-ManagedRunnerProcess" in text
    assert "exec ./run.sh" in text
    assert "RUNNER_ALLOW_RUNASROOT=1" in text
    assert "RUNNER_TRACKING_ID=" in text
    assert "watchdog_owns_wsl_child = $true" in text
    assert "watchdog_owns_wsl_child=true" in text
    assert "nohup ./run.sh" not in text


def test_install_detaches_watchdog_from_actions_process_cleanup() -> None:
    text = _text()
    assert "schema_version = 7" in text
    assert "actions_process_tracking_detached = $true" in text
    assert "actions_process_tracking_detached=true" in text
    assert "GetEnvironmentVariable('RUNNER_TRACKING_ID', 'Process')" in text
    assert "SetEnvironmentVariable('RUNNER_TRACKING_ID', $null, 'Process')" in text
    assert "SetEnvironmentVariable('RUNNER_TRACKING_ID', $previousTrackingId, 'Process')" in text
    detached = text.split(
        "$previousTrackingId = [Environment]::GetEnvironmentVariable", 1
    )[1].split("$proc.Dispose()", 1)[0]
    assert detached.index("SetEnvironmentVariable('RUNNER_TRACKING_ID', $null") < detached.index(
        "$proc.Start()"
    )


def test_current_watchdog_is_reused_without_wmi_or_interrupting_runner() -> None:
    text = _text()
    assert "Test-UserWatchdogActive" in text
    assert "Get-WatchdogMutexName" in text
    assert "$mutex.WaitOne(0)" in text
    assert "-Generation ' + $watchdogGeneration" in text
    assert "if ($watchdogActive)" in text
    assert "Write-RecoverySuccessOutput -ReusedCurrentWatchdog $true" in text
    assert "watchdog_upgrade_deferred_until_next_start=true" in text
    assert "System.Management.ManagementObjectSearcher" not in text
    assert "Win32_Process WHERE Name='powershell.exe'" not in text


def test_wsl_probe_interop_is_timeout_bounded() -> None:
    text = _text()
    assert "$wslTimeoutMilliseconds = 30000" in text
    assert "WaitForExit($wslTimeoutMilliseconds)" in text
    assert "exit_code = 124" in text
    assert "wsl_timeout" in text
    assert "runner_process_probe_timeout=true" in text
    assert "watchdog_generation = $watchdogGeneration" in text
    assert "wsl_call_timeout_seconds" in text
    assert "ConvertTo-WslBashWrapper" in text
    assert "$normalizedCommand = $Command.Replace(\"`r`n\", \"`n\").Replace(\"`r\", \"`n\")" in text
    assert "[Convert]::ToBase64String" in text
    assert "base64 -d | bash" in text
    assert "-u root -- bash -lc" in text
    assert "$psi.RedirectStandardInput" not in text
    assert "$psi.RedirectStandardOutput" not in text
    assert "$psi.RedirectStandardError" not in text
    assert ".StandardInput.Write" not in text
    assert "wsl_command_transport = 'BASE64_ARGV'" in text
    assert "wsl_standard_stream_redirection = $false" in text
    assert "probe_exit=" in text
    assert "this script will not create or replace it" in text


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


def test_watchdog_inventory_is_mutex_backed_and_wmi_independent() -> None:
    text = _text()
    assert "Local\\NEXUS-Bybit-WSL-Watchdog-v" in text
    assert "Threading.Mutex" in text
    assert "WaitOne(0)" in text
    assert "AbandonedMutexException" in text
    assert "Stop-PreviousUserWatchdogs" not in text
    assert "System.Management.ManagementObjectSearcher" not in text
    assert "Win32_Process WHERE Name='powershell.exe'" not in text
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
