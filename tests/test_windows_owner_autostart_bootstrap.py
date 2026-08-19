from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop" / "nexus-product"
ENTRY = DESKTOP / "bootstrap-main.js"
STAGER = DESKTOP / "stage-package-resources.js"
SCRIPT = ROOT / "scripts" / "install_nexus_owner_autostart_from_gui.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_owner_bootstrap_is_exact_source_interactive_and_fail_closed() -> None:
    script = read(SCRIPT)
    for marker in (
        "nexus.owner-autostart-bootstrap.v1",
        "nexus-source.bundle",
        "refs/heads/nexus-package-source",
        "git bundle verify",
        "git bundle list-heads",
        "[Environment]::UserInteractive",
        "NT AUTHORITY\\NETWORK SERVICE",
        "%LOCALAPPDATA%" if False else "LOCALAPPDATA",
        "NEXUS\\lbank-research-automation",
        "--ff-only",
        "NEXUS-ZeroTouch-Autopilot",
        "NEXUS-GitHub-Runner-Autostart",
        "-RunLevel Limited" if False else "run_level",
        "network_credentials_added = $false",
        "runner_registration_modified = $false",
        "machine_execution_policy_modified = $false",
        "elevation_requested = $false",
        "live_trading_authority = $false",
        "paper_only = $true",
    ):
        assert marker in script

    lowered = script.casefold()
    for forbidden in (
        "config.cmd",
        "github_token",
        "personalaccesstoken",
        "--token",
        "-verb runas",
        "runlevel highest",
        "set-executionpolicy",
        "remove-item -recurse",
        "get-childitem -recurse",
    ):
        assert forbidden not in lowered


def test_owner_bootstrap_uses_only_packaged_bundle_for_source_sync() -> None:
    script = read(SCRIPT)
    assert "Invoke-GitGlobal @('clone','--no-checkout','--branch','nexus-package-source',$BundlePath,$ManagedRepoRoot)" in script
    assert "Invoke-Git $ManagedRepoRoot @('fetch','--no-tags',$BundlePath,$PackageRef)" in script
    assert "remote','set-url','origin',$ExpectedGitHubUrl" in script
    assert "fetch','origin" not in script
    assert "pull" not in script.casefold()


def test_packaged_entrypoint_runs_owner_bootstrap_without_blocking_product_main() -> None:
    entry = read(ENTRY)
    for marker in (
        "install_nexus_owner_autostart_from_gui.ps1",
        "nexus-source.bundle",
        "OWNER_AUTOSTART_TIMEOUT_MS",
        "startOwnerAutostartBootstrap(sourceSha).catch",
        "nexus-owner-autostart-bootstrap.log",
        "require('./main.js')",
    ):
        assert marker in entry
    assert "shell: true" not in entry


def test_package_stager_builds_self_contained_source_bundle_and_cleans_temp_ref() -> None:
    stager = read(STAGER)
    for marker in (
        "install_nexus_owner_autostart_from_gui.ps1",
        "nexus-source.bundle",
        "refs/heads/nexus-package-source",
        "--is-shallow-repository",
        "--unshallow",
        "bundle', 'create",
        "bundle', 'verify",
        "update-ref', '-d'",
        "GITHUB_SHA",
    ):
        assert marker in stager
    assert "--token" not in stager
    assert "config.cmd" not in stager.casefold()


def test_owner_bootstrap_powershell_parses_on_windows() -> None:
    if sys.platform != "win32":
        pytest.skip("Windows PowerShell parser check is Windows-only")
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped_script = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped_script}',[ref]$tokens,[ref]$errors)|Out-Null;"
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


def test_stage_script_parses_with_node_when_available() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available on this CI image")
    completed = subprocess.run(
        [node, "--check", str(STAGER)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
