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
        "ArtifactId 10449670023",
        "f793e3a53048f6fcc02b593036fb32f496e44de5",
        "c3eacdc5253b2d9d2372f436394e8a7cbd1c1c73fc7c5fc5fbead4551d4cd82a",
        "27d5af2c182b27e3078e050b4c9bd55def1b5e045ac11873cb9c0cf6c50e0921",
        'ExpectedComputerName "DESKTOP-1R1081M"',
        'ExpectedRunnerName "NEXUS-LOCAL-RUNNER"',
    ):
        assert marker in workflow
    parsed = yaml.safe_load(workflow)
    assert isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict)
    permission_block = workflow.split("permissions:", 1)[1].split("concurrency:", 1)[0]
    assert permission_block.strip() == "contents: read"
    assert "actions/download-artifact" not in workflow


def test_installer_is_side_by_side_non_admin_and_preserves_existing_install() -> None:
    script = text(SCRIPT)
    for marker in (
        "versioned_side_by_side_portable",
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
        "workflow_token_used = $false",
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
    assert rule["workflow_permissions"] == {"contents": "read"}
    assert "write" not in rule["workflow_permissions"].values()
