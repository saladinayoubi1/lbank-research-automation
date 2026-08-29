from pathlib import Path


SCRIPT = Path("scripts/provision_nexus_bybit_wsl1_runner.ps1")
WORKFLOW = Path(".github/workflows/nexus-bybit-wsl1-fallback.yml")


def test_wsl1_bootstrap_uses_quote_safe_base64_transport():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "[Convert]::ToBase64String" in text
    assert "base64 --decode | bash" in text
    assert "Invoke-WslEncodedBash" in text
    assert "transport = 'base64_utf8_lf_to_wsl_bash'" in text


def test_wsl1_bootstrap_preserves_windows_runner_and_no_reboot_policy():
    text = SCRIPT.read_text(encoding="utf-8")
    lowered = text.lower()
    assert "windows_runner_paths_modified = $false" in text
    assert "windows_runner_service_modified = $false" in text
    assert "automatic_restart_performed = $false" in text
    assert "firmware_setting_modified = $false" in text
    assert "github_registration_token_persisted = $false" in text
    assert r"c:\actions-runner\actions-runner" not in lowered
    assert "restart-computer" not in lowered
    assert "shutdown.exe" not in lowered
    assert "bcdedit" not in lowered


def test_wsl1_bootstrap_keeps_token_out_of_encoded_script_payload():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "$env:NEXUS_RUNNER_TOKEN = $registrationToken" in text
    assert "NEXUS_RUNNER_TOKEN:NEXUS_REPOSITORY_URL" in text
    assert "./config.sh --unattended --url \"$NEXUS_REPOSITORY_URL\" --token \"$NEXUS_RUNNER_TOKEN\"" in text
    assert "$registrationToken = $null" in text


def test_physical_workflow_routes_only_to_bounded_windows_fallback():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "contains(github.event.head_commit.message, '[provision-bybit-wsl1]')" in text
    assert "scripts\\provision_nexus_bybit_wsl1_runner.ps1" in text
    permissions = text.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert "contents: read" in permissions
    assert "write" not in permissions
