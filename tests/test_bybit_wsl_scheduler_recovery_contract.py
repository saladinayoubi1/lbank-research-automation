from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
WAKE_WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-wake.yml"
DIAGNOSTIC_SCRIPT = ROOT / "scripts" / "run_nexus_bybit_wsl_runner_diagnostics.ps1"


def test_wake_is_bootstrap_independent_native_wsl_and_bounded() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")

    assert not re.search(r"(?m)^\s*uses:\s*", text)
    assert "actions/checkout" not in text
    assert "actions/upload-artifact" not in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-local]" in text
    assert "$expectedWindowsRunnerName = 'NEXUS-LOCAL-RUNNER'" in text
    assert "$distribution = 'Ubuntu'" in text
    assert "$wslRunnerRoot = '/opt/nexus-bybit-runner'" in text
    assert "$expectedWslRunnerName = 'NEXUS-BYBIT-WSL'" in text
    assert "wsl.exe" in text.lower()
    assert "schtasks.exe" not in text.lower()
    assert "legacy_scheduled_tasks_used=false" in text
    assert "windows_task_acl_modified=false" in text
    assert "runner_registration_mutated=false" in text
    assert "runner_credentials_mutated=false" in text
    assert "live_trading_authority_changed=false" in text


def test_wake_bounds_native_wsl_transport_and_fails_closed() -> None:
    text = WAKE_WORKFLOW.read_text(encoding="utf-8")

    assert "$ErrorActionPreference = 'Stop'" in text
    assert "$ProgressPreference = 'SilentlyContinue'" in text
    assert "WaitForExit(15000)" in text
    assert "$process.Kill()" in text
    assert "Bounded WSL probe timed out after 15 seconds." in text
    assert "wsl_probe_timeout_seconds=15" in text
    assert "wsl_command_transport=base64-argv" in text
    assert "ConvertTo-WslBashWrapper" in text
    assert "registration_check=pass" in text
    assert "bybit_wsl_native_wake=PASS" in text


def test_diagnostics_treat_service_wsl_visibility_as_context_limited() -> None:
    text = DIAGNOSTIC_SCRIPT.read_text(encoding="utf-8")

    assert "NEXUS Bybit WSL Runner Persistent" in text
    assert "NEXUS Bybit WSL Runner" in text
    assert "WSL_DISTRIBUTION_NOT_VISIBLE_FROM_WINDOWS_RUNNER_CONTEXT" in text
    assert "runner_health_verified = $false" in text
    assert "recovery_request_performed = $false" in text
