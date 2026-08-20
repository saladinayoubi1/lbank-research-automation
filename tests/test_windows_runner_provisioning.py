from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVISION = ROOT / "scripts" / "provision_nexus_github_runner.ps1"
BOOTSTRAP = ROOT / "scripts" / "bootstrap_nexus_runner_from_gui.ps1"
DESKTOP = ROOT / "desktop" / "nexus-product"
ENTRY = DESKTOP / "bootstrap-main.js"
STAGER = DESKTOP / "stage-package-resources.js"
PACKAGE = DESKTOP / "package.json"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_provisioner_is_pinned_verified_and_owner_scoped() -> None:
    text = read(PROVISION)
    for marker in (
        "nexus.runner-provision.v1",
        "$RunnerVersion = '2.336.0'",
        "d59123a43003e357b0805b5d0f611d0bd2f65ab67d51bd070dd4e7a0f685c162",
        "https://github.com/actions/runner/releases/download/",
        "Get-FileHash",
        "RUNNER_ARCHIVE_HASH_MISMATCH",
        "[Environment]::UserInteractive",
        "NT AUTHORITY\\SYSTEM",
        "NT AUTHORITY\\NETWORK SERVICE",
        "LOCALAPPDATA",
        "NEXUS\\actions-runner",
        "UNMANAGED_RUNNER_ROOT_REJECTED",
        "NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN",
        "REGISTRATION_TOKEN_REQUIRED",
        "registration_token_persisted = $false",
        "registration_token_logged = $false",
        "machine_execution_policy_modified = $false",
        "elevation_requested = $false",
        "service_installed = $false",
        "live_trading_authority = $false",
        "paper_only = $true",
    ):
        assert marker in text
    assert text.index("Get-FileHash -LiteralPath $tmp") < text.index("Move-Item -LiteralPath $tmp -Destination $archive -Force")
    lowered = text.casefold()
    assert "set-executionpolicy" not in lowered
    assert "-verb runas" not in lowered
    assert "personalaccesstoken" not in lowered
    assert "github_token" not in lowered


def test_provisioner_registers_only_explicitly_authorized_managed_runner() -> None:
    text = read(PROVISION)
    for marker in (
        "config.cmd",
        "'--unattended'",
        "'--url', $ExpectedGitHubUrl",
        "'--token', $Token",
        "'--name', $Name",
        "'--work', '_work'",
        "'--labels', 'nexus-local'",
        "bootstrap_nexus_runner_from_gui.ps1",
        "RUNNER_PROVISIONED",
    ):
        assert marker in text
    assert "--no-default-labels" not in text
    assert "--replace" not in text
    assert "Remove-Item Env:NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN" in text


def test_existing_fail_closed_gui_bootstrap_still_never_mutates_registration() -> None:
    text = read(BOOTSTRAP).casefold()
    assert "config.cmd" not in text
    assert "--token" not in text
    assert "runner_registered = $false" in text


def test_desktop_packages_and_invokes_provisioner_only_after_runner_not_found() -> None:
    package = json.loads(read(PACKAGE))
    resources = {(item.get("from"), item.get("to")) for item in package["build"]["extraResources"]}
    assert ("sidecar/provision_nexus_github_runner.ps1", "scripts/provision_nexus_github_runner.ps1") in resources

    stager = read(STAGER)
    assert "copyScript('provision_nexus_github_runner.ps1')" in stager

    entry = read(ENTRY)
    for marker in (
        "RUNNER_PROVISION_TIMEOUT_MS",
        "provision_nexus_github_runner.ps1",
        "NEXUS_GITHUB_RUNNER_REGISTRATION_TOKEN",
        "RUNNER_NOT_FOUND",
        "startRunnerProvisioning",
        "reconcileRunnerFromGui",
    ):
        assert marker in entry
    assert entry.index("RUNNER_NOT_FOUND") < entry.index("startRunnerProvisioning(sourceSha)")
    assert "shell: true" not in entry
    assert "config.cmd" not in entry.casefold()
