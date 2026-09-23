from pathlib import Path
import hashlib
import re


ROOT = Path(__file__).resolve().parents[1]
WAKE_WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-wake.yml"
DIAGNOSTIC_SCRIPT = ROOT / "scripts" / "run_nexus_bybit_wsl_runner_diagnostics.ps1"
WATCHDOG_SCRIPT = ROOT / "scripts" / "install_nexus_bybit_wsl_user_startup.ps1"


def _git_blob_sha(path: Path) -> str:
    payload = path.read_bytes()
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload, usedforsecurity=False).hexdigest()


def test_wake_is_bootstrap_independent_and_installs_durable_user_watchdog() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")

    assert not re.search(r"(?m)^\s*uses:\s*", text)
    assert "actions/checkout" not in text
    assert "actions/upload-artifact" not in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-local]" in text
    assert "$expectedWindowsRunnerName = 'NEXUS-LOCAL-RUNNER'" in text
    assert "NEXUS_BYBIT_WSL_STARTUP_SCRIPT_BLOB_SHA" in text
    assert "scripts\\install_nexus_bybit_wsl_user_startup.ps1" in text
    assert "Invoke-WebRequest" in text
    assert "Get-GitBlob" in text
    assert "-Mode Install" in text
    assert "-Distribution Ubuntu" in text
    assert "-RunnerRoot /opt/nexus-bybit-runner" in text
    assert "-ExpectedRunnerName NEXUS-BYBIT-WSL" in text
    assert "schtasks.exe" not in text.lower()
    assert "task_scheduler_used=false" in text
    assert "windows_task_acl_modified=false" in text
    assert "runner_registration_mutated=false" in text
    assert "runner_credentials_mutated=false" in text
    assert "live_trading_authority_changed=false" in text


def test_wake_pin_matches_current_watchdog_git_blob() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"NEXUS_BYBIT_WSL_STARTUP_SCRIPT_BLOB_SHA:\s*([0-9a-f]{40})", text)
    assert match is not None
    assert match.group(1) == _git_blob_sha(WATCHDOG_SCRIPT)


def test_wake_pins_source_and_requires_detached_live_watchdog() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")

    assert "$ErrorActionPreference = 'Stop'" in text
    assert "$ProgressPreference = 'SilentlyContinue'" in text
    assert "$attempt -le 4" in text
    assert "raw.githubusercontent.com/$expectedRepository/$targetSha" in text
    assert "bybit_wsl_watchdog_blob=" in text
    assert "USER_CONTEXT_MANAGED_CHILD_LIVENESS_SELF_HEAL_ACTIVE" in text
    assert "actions_process_tracking_detached" in text
    assert "watchdog_generation -ne 9" in text
    assert "wsl_command_transport -ne 'BASE64_ARGV'" in text
    assert "wsl_standard_stream_redirection -ne $false" in text
    assert "Start-Sleep -Seconds 20" in text
    assert "Threading.Mutex" in text
    assert "$watchdogMutex.WaitOne(0)" in text
    assert "Win32_Process WHERE Name='powershell.exe'" not in text
    assert "System.Management.ManagementObjectSearcher" not in text
    assert "post_install_watchdog_process=RUNNING" in text
    assert "bybit_wsl_durable_recovery=PASS" in text


def test_diagnostics_treat_service_wsl_visibility_as_context_limited() -> None:
    text = DIAGNOSTIC_SCRIPT.read_text(encoding="utf-8")

    assert "NEXUS Bybit WSL Runner Persistent" in text
    assert "NEXUS Bybit WSL Runner" in text
    assert "WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT" in text
    assert "runner_health_verified = $false" in text
    assert "recovery_request_performed = $false" in text
