from pathlib import Path


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


def test_recovery_uses_per_user_startup_and_bounded_watchdog() -> None:
    text = _text()
    assert "GetFolderPath('Startup')" in text
    assert "BybitWSLUserStartup" in text
    assert "-Mode Watch" in text
    assert "Start-Sleep -Seconds 15" in text
    assert "Local\\NEXUS-Bybit-WSL-Watchdog-" in text
    assert "pgrep -f '$RunnerRoot/bin/[R]unner.Listener'" in text
    assert "nohup ./run.sh" in text
    assert "RUNNER_ALLOW_RUNASROOT=1" in text
    assert "RUNNER_TRACKING_ID=" in text


def test_recovery_startup_launcher_is_fully_hidden() -> None:
    text = _text()
    assert "NEXUS-Bybit-WSL-User-Startup.vbs" in text
    assert 'CreateObject("WScript.Shell")' in text
    assert 'shell.Run "' in text
    assert '", 0, False' in text
    assert "popup_launcher_used = $false" in text
    assert "NEXUS-Bybit-WSL-User-Startup.cmd" in text  # cleanup of the superseded launcher
    assert "Remove-Item -LiteralPath $legacyStartupCmd -Force" in text


def test_recovery_does_not_expand_trading_or_windows_authority() -> None:
    text = _text()
    assert "windows_acl_modified = $false" in text
    assert "windows_service_modified = $false" in text
    assert "private_exchange_credentials_used = $false" in text
    assert "live_trading_authority_changed = $false" in text
    for forbidden in ("icacls", "sc.exe", "New-Service", "Set-Acl", "api_key", "api_secret"):
        assert forbidden.lower() not in text.lower()
