from pathlib import Path


SCRIPT = Path("scripts/provision_nexus_bybit_wsl_runner.ps1")


def script_text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_kernel_bootstrap_is_limited_to_proven_wsl2_kernel_failure() -> None:
    text = script_text()
    assert "WSL 2 requires an update to its kernel component" in text
    assert "Install-Wsl2KernelUpdate" in text
    assert "distribution_install_retried_after_kernel_update" in text


def test_kernel_package_uses_official_microsoft_x64_url_and_signature_gate() -> None:
    text = script_text()
    assert "https://wslstorestorage.blob.core.windows.net/wslblob/wsl_update_x64.msi" in text
    assert "Get-AuthenticodeSignature" in text
    assert "CN=Microsoft Corporation" in text
    assert "WSL_KERNEL_UPDATE_SIGNATURE_INVALID" in text


def test_kernel_update_never_reboots_automatically() -> None:
    text = script_text()
    assert "/norestart" in text
    assert "automatic_restart_performed = $false" in text
    assert "WSL_KERNEL_UPDATE_RESTART_REQUIRED" in text
    assert "@(1641, 3010)" in text


def test_kernel_update_preserves_existing_windows_runner_boundary() -> None:
    text = script_text()
    assert "windows_runner_paths_modified = $false" in text
    assert 'Write-Host "windows_runner_paths_modified=false"' in text
    assert "github_registration_token_persisted = $false" in text
    assert "bybit_private_credentials_used = $false" in text


def test_kernel_update_records_verifiable_evidence() -> None:
    text = script_text()
    for marker in (
        "wsl_kernel_update_attempted",
        "wsl_kernel_update_signature_valid",
        "wsl_kernel_update_signature_status",
        "wsl_kernel_update_signer_subject",
        "wsl_kernel_update_signer_thumbprint",
        "wsl_kernel_update_download_sha256",
        "wsl_kernel_update_exit_code",
    ):
        assert marker in text
