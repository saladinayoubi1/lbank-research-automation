from __future__ import annotations

from pathlib import Path


SCRIPT = Path("scripts/diagnose_nexus_bybit_wsl_runner.ps1")
WORKFLOW = Path(".github/workflows/nexus-local-runner.yml")


def test_wsl_bybit_diagnostic_is_read_only_and_public_data_only() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.casefold()

    assert "https://api.bybit.com/v5/market/time" in text
    assert "private_credentials_used = $false" in text
    assert "proxy_or_vpn_configured = $false" in text
    assert "Get-WindowsOptionalFeature" in text
    assert "wsl.exe" in text

    for forbidden in (
        "enable-windowsoptionalfeature",
        "disable-windowsoptionalfeature",
        "install-windowsfeature",
        "restart-computer",
        "shutdown.exe",
        "config.sh",
        "registration-token",
        "api_key",
        "api_secret",
    ):
        assert forbidden not in lowered


def test_local_runner_exposes_bounded_wsl_bybit_diagnostic() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "- bybit-wsl-status" in text
    assert "Diagnose WSL and Bybit public-network eligibility" in text
    assert "scripts\\diagnose_nexus_bybit_wsl_runner.ps1" in text
    assert "Upload WSL and Bybit public-network evidence" in text
    assert "nexus-bybit-wsl-runner-diagnostic-${{ github.run_id }}" in text
    assert "if-no-files-found: error" in text
