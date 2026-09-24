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
DOWNLOADER = ROOT / "scripts" / "download_github_actions_artifact_http11.ps1"
RESOLVER = ROOT / "scripts" / "resolve_nexus_persistent_artifact.ps1"
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
        "Resolve exact-source NEXUS persistent package",
        "resolve_nexus_persistent_artifact.ps1",
        "-SourceSha $env:GITHUB_SHA",
        "nexus-build-verification.yml",
        "nexus-windows-persistent-unpacked",
        "steps.package_meta.outputs.artifact_run_id",
        "steps.package_meta.outputs.artifact_id",
        "steps.package_meta.outputs.source_sha",
        "steps.package_meta.outputs.archive_sha256",
        "steps.package_meta.outputs.archive_bytes",
        "steps.package_download.outputs.inner_sha256",
        'ExpectedComputerName "DESKTOP-1R1081M"',
        'ExpectedRunnerName "NEXUS-LOCAL-RUNNER"',
        "Download exact NEXUS persistent package via resilient HTTP/1.1 transport",
        "download_github_actions_artifact_http11.ps1",
        "GITHUB_TOKEN: ${{ github.token }}",
        "-UsePreloadedPackage",
    ):
        assert marker in workflow
    for stale in (
        "ArtifactRunId 36026328756",
        "ArtifactId 10818899755",
        "6906679596a6f2f01d6da63ae0620e7a1c78ec6d",
        "4deddbc6c26324a8ea77eb7b825cdf3848ff13971d89ec49c65288b9070f8921",
        "1445007c0316f0bdb0aa64f60b0aeeddd4c287e527c6b37399a0de6798698f54",
        "217220273",
    ):
        assert stale not in workflow
    parsed = yaml.safe_load(workflow)
    assert isinstance(parsed, dict) and isinstance(parsed.get("jobs"), dict)
    assert parsed["permissions"] == {"actions": "read", "contents": "read"}
    assert "actions/download-artifact@" not in workflow


def test_exact_source_artifact_resolver_requires_successful_main_push_and_named_artifact() -> None:
    script = text(RESOLVER)
    for marker in (
        "head_sha",
        "conclusion -eq 'success'",
        "event -in @('push', 'workflow_dispatch')",
        "head_branch -eq 'main'",
        "actor.login",
        "repositoryOwner",
        "nexus-build-verification.yml",
        "nexus-windows-persistent-unpacked",
        "workflow_run.head_sha",
        "artifact_run_id",
        "artifact_id",
        "archive_sha256",
        "archive_bytes",
        "GITHUB_OUTPUT",
        "NEXUS_PERSISTENT_ARTIFACT_RESOLVE=PASS",
    ):
        assert marker in script
    assert "http://" not in script


def test_resilient_artifact_downloader_is_metadata_and_digest_bound() -> None:
    script = text(DOWNLOADER)
    for marker in (
        "metadata.workflow_run.id",
        "metadata.workflow_run.head_sha",
        "metadata.digest",
        "ExpectedArchiveBytes",
        "--http1.1",
        "--range",
        "--speed-time",
        "--speed-limit",
        "NEXUS_ARTIFACT_RANGE_PROGRESS",
        "$parallelChunks = 4",
        "$chunkBytes = 1MB",
        "Artifact destination escaped RUNNER_TEMP",
        "Get-FileHash",
        "SHA256SUMS.txt",
        "manifestInnerSha256",
        "actualInnerSha256",
        "inner_sha256=",
        "NEXUS_ARTIFACT_HTTP11_DOWNLOAD=PASS",
    ):
        assert marker in script
    assert "http://" not in script
    # Windows 10 ships curl 7.55.1 on the Lenovo; chunk retries are implemented by PowerShell.
    assert "--retry-all-errors" not in script
    assert "--continue-at" not in script
    assert "Start-Process -FilePath 'curl.exe'" in script
    assert "Get-SignedArtifactUrl" in script
    assert "$exitCodeKnown = $null -ne $exitCode" in script
    assert "$actualPartBytes -ne $expectedPartBytes" in script
    assert "$stderrRaw = Get-Content -LiteralPath $part.Stderr -Raw -ErrorAction SilentlyContinue" in script
    assert "if ($null -ne $stderrRaw) { $stderr = $stderrRaw.Trim() }" in script
    assert "([string](Get-Content -LiteralPath $part.Stderr -Raw -ErrorAction SilentlyContinue)).Trim()" not in script


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
        "NEXUS Personal Pro.lnk",
        "startup_shortcut_created = $false",
        "startup_shortcut_created = $true",
        "NEXUS_APP_AUTOSTART_SHORTCUT=",
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
    for path in (SCRIPT, DOWNLOADER, RESOLVER):
        escaped = str(path).replace("'", "''")
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
