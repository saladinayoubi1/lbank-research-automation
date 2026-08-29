from __future__ import annotations

from pathlib import Path


SCRIPT = Path("scripts/provision_nexus_bybit_wsl_runner.ps1")
WORKFLOW = Path(".github/workflows/nexus-local-runner.yml")


def test_wsl_linux_runner_provisioning_is_isolated_pinned_and_restart_safe() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.casefold()

    assert "NEXUS-BYBIT-WSL" in text
    assert "nexus-bybit-network" in text
    assert '[string]$RunnerVersion = "2.336.0"' in text
    assert 'actions-runner-linux-x64-$RunnerVersion.tar.gz' in text
    assert "04cf0be1aff4c3ec3554466c39124ca250e3effd8873bb7e8d68535aa9505d5d" in text
    assert "ubuntu-noble-wsl-amd64-24.04lts.rootfs.tar.gz" in text
    assert "2a790896740b14d637dbdc583cce1ba081ac53b9e9cdb46dc09a2f73abbd9934" in text
    assert "cloud-images.ubuntu.com" in text
    assert "pinned_ubuntu_rootfs_import" in text
    assert "--import" in text
    assert "elseif ($help.output -match '--import')" not in text
    assert "WSL_NONINTERACTIVE_INSTALL_UNAVAILABLE" not in text
    assert "ubuntu_rootfs_download_verified" in text
    assert "UBUNTU_ROOTFS_CHECKSUM_MISMATCH" in text
    assert "WSL_IMPORT_LOCATION_NOT_EMPTY" in text
    assert "Get-FileHash -LiteralPath $rootfsArchive -Algorithm SHA256" in text
    assert "Remove-Item -LiteralPath $rootfsArchive -Force" in text
    assert "sha256sum --check --status" in text
    assert "wsl.exe" in text
    assert "--no-launch" in text
    assert "/opt/nexus-bybit-runner" in text
    assert "New-ScheduledTaskAction" in text
    assert "Register-ScheduledTask" in text
    assert "automatic_restart_performed = $false" in text
    assert "windows_runner_paths_modified = $false" in text
    assert "github_registration_token_persisted = $false" in text
    assert "bybit_private_credentials_used = $false" in text
    assert "NEXUS_RUNNER_TOKEN/w" in text
    assert "Remove-Item Env:NEXUS_RUNNER_TOKEN" in text
    assert "READY_FOR_GITHUB_VALIDATION" in text
    assert "WSL_RUNNER_PROVISIONING_FAILED" in text
    assert "provisioning_error_class" in text

    for forbidden in (
        "restart-computer",
        "shutdown.exe",
        "stop-computer",
        "disable-windowsoptionalfeature",
        "api_key",
        "api_secret",
        "c:\\actions-runner",
    ):
        assert forbidden not in lowered


def test_local_runner_exposes_explicit_wsl_linux_provisioning_task() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "- bybit-wsl-provision" in text
    assert "inputs.task == 'bybit-wsl-provision'" in text
    assert "scripts\\provision_nexus_bybit_wsl_runner.ps1" in text
    assert "Upload Bybit WSL Linux runner provisioning evidence" in text
    assert "nexus-bybit-wsl-provisioning-${{ github.run_id }}" in text
    assert "if-no-files-found: error" in text
    assert "path: build/bybit-wsl-provisioning/evidence.json" in text
