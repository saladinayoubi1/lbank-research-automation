from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
SCRIPT = ROOT / "scripts" / "install_and_smoke_nexus_personal_pro.ps1"
POLICY = ROOT / "security" / "workflow-permissions-policy-v1.json"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_install_route_is_owner_main_exact_laptop_and_digest_bound() -> None:
    workflow = text(WORKFLOW)
    for marker in (
        "[install-app]",
        "name: NEXUS Local Runner",
        "github.actor == github.repository_owner",
        "runs-on: [self-hosted, Windows, X64, nexus-local]",
        "ArtifactId 10660551978",
        "2a30473695b7464291b84a77f690daf12a4a0873",
        "505e9ac5f61acf4a12910a9a96f83f2886cf4e79089c1958fb14649d0f8245bf",
        'ArtifactName "nexus-windows-persistent-unpacked"',
        'ExpectedComputerName "DESKTOP-1R1081M"',
        'ExpectedRunnerName "NEXUS-LOCAL-RUNNER"',
        "Download exact NEXUS persistent package",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
        "run-id: 35646726924",
        "github-token: ${{ github.token }}",
        "-UsePreloadedPackage",
    ):
        assert marker in workflow
    parsed = yaml.safe_load(workflow)
    assert isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict)
    assert parsed["permissions"] == {"actions": "read", "contents": "read"}
    assert "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093" in workflow


def test_installer_is_side_by_side_non_admin_and_preserves_existing_install() -> None:
    script = text(SCRIPT)
    for marker in (
        "versioned_side_by_side_unpacked",
        "previous_install_removed = $false",
        "previous_app_data_removed = $false",
        "registry_installation_changed = $false",
        "setup_executable_invoked = $false",
        "uninstaller_invoked = $false",
        "WindowsBuiltInRole]::Administrator",
        "Elevated installation is forbidden",
        "NEXUS Personal Pro 5.1.0.lnk",
        "RUNNER_TRACKING_ID",
        "existing_owner_gh_cli",
        "actions_download_artifact",
        "[switch]$UsePreloadedPackage",
        "workflow_token_used = $false",
        "workflow_token_used = $true",
        "gh.Source run download",
        "SetEnvironmentVariable('GITHUB_TOKEN', $null, 'Process')",
    ):
        assert marker in script
    lowered = script.casefold()
    for forbidden in (
        "-verb runas",
        "uninstall.exe",
        "remove-appxpackage",
        "config.cmd",
        "set-executionpolicy",
        "reg.exe add",
        "live_trading_authority = $true",
    ):
        assert forbidden not in lowered


def test_physical_smoke_requires_visible_ui_and_all_product_safety_contracts() -> None:
    script = text(SCRIPT)
    for marker in (
        "[Environment]::UserInteractive",
        "Get-Process -Name explorer",
        "Wait-ForVisibleNewWindow",
        "Wait-ForHealthySupervisor",
        "/api/product/overview",
        "/api/product/paper",
        "/api/product/live",
        "/api/product/offline",
        "/api/product/mission/full",
        "/api/product/build-evidence",
        "/api/product/strategies/evidence",
        "Deterministic Risk authority is missing",
        "Live trading authority widened",
        "NEXUS_WINDOWS_APP_INSTALL=PASS",
    ):
        assert marker in script


def test_install_artifact_transport_cleanup_is_narrow_and_fail_closed() -> None:
    script = text(SCRIPT)
    assert "Test-PathWithin $PackageRoot $env:RUNNER_TEMP" in script
    assert "^nexus-personal-pro-package-[0-9]+$" in script
    assert "Refusing to remove a package transport outside RUNNER_TEMP" in script
    assert "^nexus-app-smoke-[0-9]+$" in script
    assert "Remove-Item -LiteralPath $PackageRoot -Recurse -Force" in script
    assert "Remove-Item -LiteralPath $env:USERPROFILE" not in script


@pytest.mark.skipif(os.name != "nt", reason="PowerShell parser proof requires Windows")
def test_install_script_parses_in_windows_powershell() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell, "Windows PowerShell is required on windows-latest"
    escaped = str(SCRIPT).replace("'", "''")
    command = (
        f"$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "$messages=@($errors|ForEach-Object{$_.Message});if($messages.Count){$messages|ForEach-Object{Write-Error $_};exit 1}"
    )
    subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        text=True,
        capture_output=True,
    )


def test_permission_policy_tracks_cross_run_artifact_read() -> None:
    policy = json.loads(text(POLICY))
    rule = policy["workflows"][".github/workflows/nexus-local-runner.yml"]
    assert rule["workflow_permissions"] == {"actions": "read", "contents": "read"}
    assert "write" not in rule["workflow_permissions"].values()
