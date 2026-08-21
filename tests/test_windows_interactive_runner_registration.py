from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "register_nexus_runner_interactive.ps1"


def read() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_registration_helper_is_repo_bound_pinned_and_fail_closed() -> None:
    text = read()
    for marker in (
        "saladinayoubi1/lbank-research-automation",
        "2.336.0",
        "d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162",
        "RUNNER_ARCHIVE_HASH_MISMATCH",
        "UNMANAGED_RUNNER_ROOT_REJECTED",
        "NEXUS-LOCAL-RUNNER",
        "--replace",
        "--labels 'nexus-local'",
    ):
        assert marker in text


def test_registration_helper_acquires_short_lived_token_without_persisting_it() -> None:
    text = read()
    for marker in (
        "& $Gh auth login",
        "--web",
        "--scopes repo",
        "actions/runners/registration-token",
        "registration_token_persisted = $false",
        "registration_token_logged = $false",
        "registration_token_written_to_disk = $false",
        "$registrationToken = $null",
    ):
        assert marker in text
    token_body = text[text.index("function Get-RegistrationToken"):text.index("function Register-Runner")]
    assert "Set-Content" not in token_body
    assert "Add-Content" not in token_body


def test_github_cli_fallback_is_official_and_checksum_verified() -> None:
    text = read()
    for marker in (
        "https://api.github.com/repos/cli/cli/releases/latest",
        "_windows_amd64\\.zip",
        "_checksums\\.txt",
        "Get-FileHash",
        "GH_ARCHIVE_HASH_MISMATCH",
        "tools\\gh",
    ):
        assert marker in text


def test_runner_persistence_uses_task_scheduler_com_not_cim_or_elevation() -> None:
    text = read()
    for marker in (
        "Schedule.Service",
        "RegisterTaskDefinition",
        "Principal.LogonType = 3",
        "Principal.RunLevel = 0",
        "Triggers.Create(9)",
        "NEXUS-GitHub-Runner-Autostart",
        "ExecutionTimeLimit = 'PT0S'",
        "RestartCount = 999",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "new-scheduledtaskaction" not in lowered
    assert "-runlevel highest" not in lowered
    assert "set-executionpolicy" not in lowered
    assert "runas" not in lowered
    assert "config.cmd --unattended" not in lowered  # invocation stays argument-safe via call operator


def test_registration_helper_preserves_nexus_authority_boundaries() -> None:
    text = read()
    for marker in (
        "service_installed = $false",
        "elevation_requested = $false",
        "machine_execution_policy_modified = $false",
        "paper_only = $true",
        "live_trading_authority = $false",
    ):
        assert marker in text


def test_registration_helper_powershell_parses_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parser check is Windows-only")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count -gt 0){$errors|ForEach-Object{Write-Error $_.Message};exit 1}"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
