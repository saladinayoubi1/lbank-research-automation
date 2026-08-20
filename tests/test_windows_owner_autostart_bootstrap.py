from __future__ import annotations

import json
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
        "nexus-source-seed.git",
        "refs/heads/nexus-package-source",
        "--git-dir",
        "fsck",
        "[Environment]::UserInteractive",
        "NT AUTHORITY\\NETWORK SERVICE",
        "LOCALAPPDATA",
        "NEXUS\\lbank-research-automation",
        "--no-local",
        "NEXUS-ZeroTouch-Autopilot",
        "NEXUS-GitHub-Runner-Autostart",
        "run_level",
        "managed_checkout_updated_from_package_seed",
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
        "reset --hard",
        "git clean",
    ):
        assert forbidden not in lowered


def test_owner_bootstrap_uses_only_packaged_seed_for_initial_and_existing_source() -> None:
    script = read(SCRIPT)
    assert "Invoke-GitGlobal -GitArguments @('clone','--no-local','--no-checkout','--branch','nexus-package-source',$SeedRepoPath,$ManagedRepoRoot)" in script
    assert "remote','set-url','origin',$ExpectedGitHubUrl" in script
    assert "'fetch','--no-tags','--update-shallow',$SeedRepoPath,$PackageRef" in script
    assert "'rev-parse','FETCH_HEAD'" in script
    assert "'checkout','-B','main','FETCH_HEAD'" in script
    assert "packaged seed fetch mismatch" in script
    assert "managed checkout reconciliation failed" in script
    assert "fetch','origin" not in script
    assert "pull" not in script.casefold()


def test_owner_bootstrap_native_argv_binding_never_uses_automatic_args() -> None:
    script = read(SCRIPT)
    assert "function Invoke-Git([string]$Root, [string[]]$GitArguments)" in script
    assert "function Invoke-GitGlobal([string[]]$GitArguments)" in script
    assert "[string[]]$Args" not in script
    assert "$args =" not in script.casefold()
    assert "Invoke-NativeCapture -Executable $git -WorkingDirectory $Root -Arguments $GitArguments" in script
    assert "Invoke-NativeCapture -Executable $git -WorkingDirectory '' -Arguments $GitArguments" in script
    assert "Invoke-GitGlobal -GitArguments @('--git-dir',$SeedRepoPath,'rev-parse',$PackageRef)" in script
    assert "Invoke-Git -Root $ManagedRepoRoot -GitArguments @('rev-parse','HEAD')" in script
    assert "-Arguments $installerArguments" in script


def test_existing_managed_checkout_must_be_canonical_and_tracked_clean_before_reconcile() -> None:
    script = read(SCRIPT)
    validate = script.index("function Validate-ExistingManagedRepo")
    reconcile = script.index("function Reconcile-ExistingManagedRepo")
    prepare = script.index("function Prepare-ManagedRepo")
    section = script[validate:reconcile]
    assert "Assert-CanonicalRemote $ManagedRepoRoot" in section
    assert "Assert-TrackedClean $ManagedRepoRoot" in section
    assert "managed checkout has tracked owner changes; refusing automatic replacement" in script
    assert validate < reconcile < prepare
    prepare_section = script[prepare:script.index("function Get-PowerShellExe")]
    assert "Validate-ExistingManagedRepo" in prepare_section
    assert "Reconcile-ExistingManagedRepo" in prepare_section


def _git(*args: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def test_shallow_packaged_seed_can_reconcile_an_older_clean_checkout_without_network(tmp_path: Path) -> None:
    if not shutil.which("git"):
        pytest.skip("git is unavailable")

    source = tmp_path / "source"
    source.mkdir()
    _git("init", "-b", "main", cwd=source)
    _git("config", "user.email", "nexus-test@example.invalid", cwd=source)
    _git("config", "user.name", "NEXUS Test", cwd=source)
    (source / "payload.txt").write_text("old\n", encoding="utf-8")
    _git("add", "payload.txt", cwd=source)
    _git("commit", "-m", "old", cwd=source)
    old_sha = _git("rev-parse", "HEAD", cwd=source)

    (source / "payload.txt").write_text("new\n", encoding="utf-8")
    _git("add", "payload.txt", cwd=source)
    _git("commit", "-m", "new", cwd=source)
    new_sha = _git("rev-parse", "HEAD", cwd=source)
    _git("branch", "nexus-package-source", new_sha, cwd=source)

    managed = tmp_path / "managed"
    _git("clone", str(source), str(managed))
    _git("checkout", "-B", "main", old_sha, cwd=managed)
    assert _git("status", "--porcelain=v1", "--untracked-files=no", cwd=managed) == ""

    seed = tmp_path / "nexus-source-seed.git"
    _git(
        "clone",
        "--bare",
        "--depth",
        "1",
        "--branch",
        "nexus-package-source",
        source.as_uri(),
        str(seed),
    )
    assert (seed / "shallow").is_file()
    assert _git("--git-dir", str(seed), "rev-parse", "refs/heads/nexus-package-source") == new_sha

    _git("fetch", "--no-tags", "--update-shallow", str(seed), "refs/heads/nexus-package-source", cwd=managed)
    assert _git("rev-parse", "FETCH_HEAD", cwd=managed) == new_sha
    _git("checkout", "-B", "main", "FETCH_HEAD", cwd=managed)

    assert _git("rev-parse", "HEAD", cwd=managed) == new_sha
    assert (managed / "payload.txt").read_text(encoding="utf-8") == "new\n"
    assert _git("status", "--porcelain=v1", "--untracked-files=no", cwd=managed) == ""


def test_packaged_entrypoint_runs_owner_bootstrap_without_blocking_product_main() -> None:
    entry = read(ENTRY)
    for marker in (
        "install_nexus_owner_autostart_from_gui.ps1",
        "nexus-source-seed.git",
        "OWNER_AUTOSTART_TIMEOUT_MS",
        "startOwnerAutostartBootstrap(sourceSha).catch",
        "nexus-owner-autostart-bootstrap.log",
        "require('./main.js')",
    ):
        assert marker in entry
    assert "shell: true" not in entry


def test_package_config_carries_owner_helper_and_exact_source_seed() -> None:
    package = json.loads(read(DESKTOP / "package.json"))
    resources = {(item.get("from"), item.get("to")) for item in package["build"]["extraResources"]}
    assert ("sidecar/install_nexus_owner_autostart_from_gui.ps1", "scripts/install_nexus_owner_autostart_from_gui.ps1") in resources
    assert ("sidecar/nexus-source-seed.git", "nexus-source-seed.git") in resources
    dist = package["scripts"]["dist:win"]
    assert "stage-package-resources.js" in dist
    assert dist.index("stage-package-resources.js") < dist.index("electron-builder")


def test_package_stager_builds_shallow_exact_source_seed_and_cleans_temp_ref() -> None:
    stager = read(STAGER)
    for marker in (
        "install_nexus_owner_autostart_from_gui.ps1",
        "nexus-source-seed.git",
        "refs/heads/nexus-package-source",
        "--depth', '1'",
        "--bare",
        "--branch', 'nexus-package-source'",
        "pathToFileURL",
        "update-ref', '-d'",
        "GITHUB_SHA",
        "shallow",
    ):
        assert marker in stager
    assert "--unshallow" not in stager
    assert "bundle" not in stager.casefold()
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
