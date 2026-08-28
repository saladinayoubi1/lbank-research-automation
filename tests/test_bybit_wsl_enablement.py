from __future__ import annotations

from pathlib import Path


SCRIPT = Path("scripts/enable_nexus_bybit_wsl.ps1")
WORKFLOW = Path(".github/workflows/nexus-local-runner.yml")


def test_wsl_enablement_is_elevated_bounded_and_never_restarts_automatically() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.casefold()

    assert "-Verb RunAs" in text
    assert "Enable-WindowsOptionalFeature" in text
    assert "Microsoft-Windows-Subsystem-Linux" in text
    assert "VirtualMachinePlatform" in text
    assert "-NoRestart" in text
    assert "automatic_restart_performed = $false" in text
    assert "private_credentials_used = $false" in text
    assert "proxy_or_vpn_configured = $false" in text

    for forbidden in (
        "restart-computer",
        "shutdown.exe",
        "stop-computer",
        "disable-windowsoptionalfeature",
        "config.sh",
        "registration-token",
        "api_key",
        "api_secret",
    ):
        assert forbidden not in lowered


def test_local_runner_exposes_explicit_wsl_enablement_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "- bybit-wsl-enable" in text
    assert "inputs.task == 'bybit-wsl-enable'" in text
    assert "scripts\\enable_nexus_bybit_wsl.ps1" in text
    assert "Upload WSL enablement evidence" in text
    assert "nexus-bybit-wsl-enablement-${{ github.run_id }}" in text
    assert "if-no-files-found: error" in text
