from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "nexus_runtime_worker.js"
STAGER = ROOT / "desktop" / "nexus-product" / "stage-package-resources.js"
PACKAGE = ROOT / "desktop" / "nexus-product" / "package.json"
WRAPPER = ROOT / "scripts" / "install_nexus_owner_autostart_with_self_heal.ps1"
MANUAL_INSTALL = ROOT / "INSTALL_NEXUS_AUTOSTART.cmd"
BOOTSTRAP_MAIN = ROOT / "desktop" / "nexus-product" / "bootstrap-main.js"


def test_self_hosted_github_runtime_worker_yields_after_one_cycle() -> None:
    text = RUNTIME.read_text(encoding="utf-8")
    for marker in (
        "process.env.GITHUB_ACTIONS === 'true'",
        "process.env.RUNNER_ENVIRONMENT === 'self-hosted-windows'",
        "if (once || boundedGitHubSelfHosted)",
        "bounded_self_hosted_github_cycle=complete",
    ):
        assert marker in text


def test_packaged_owner_bootstrap_preserves_canonical_tasks_then_enables_same_task_self_heal() -> None:
    stager = STAGER.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP_MAIN.read_text(encoding="utf-8")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))

    assert "copyScript('install_nexus_owner_autostart_from_gui.ps1', 'install_nexus_owner_autostart_core.ps1')" in stager
    assert "copyScript('install_nexus_owner_autostart_with_self_heal.ps1', 'install_nexus_owner_autostart_from_gui.ps1')" in stager
    assert "scriptName: 'install_nexus_owner_autostart_from_gui.ps1'" in bootstrap

    resources = {(row.get("from"), row.get("to")) for row in package["build"]["extraResources"]}
    assert ("sidecar/install_nexus_owner_autostart_from_gui.ps1", "scripts/install_nexus_owner_autostart_from_gui.ps1") in resources
    assert ("sidecar/install_nexus_owner_autostart_core.ps1", "scripts/install_nexus_owner_autostart_core.ps1") in resources

    for marker in (
        "install_nexus_owner_autostart_core.ps1",
        "enable_nexus_runner_self_heal.ps1",
        "NEXUS\\lbank-research-automation",
        "[Environment]::UserInteractive",
        "NT AUTHORITY\\NETWORK SERVICE",
        "CreateNoWindow = $true",
        "NEXUS_OWNER_AUTOSTART_AND_SELF_HEAL=SUCCESS",
    ):
        assert marker in wrapper
    lowered = wrapper.casefold()
    for forbidden in ("config.cmd", "--token", "-verb runas", "set-executionpolicy"):
        assert forbidden not in lowered


def test_manual_canonical_install_also_enables_self_heal() -> None:
    text = MANUAL_INSTALL.read_text(encoding="utf-8")
    runner_install = text.index("nexus_github_runner_autostart.ps1")
    self_heal = text.index("enable_nexus_runner_self_heal.ps1")
    assert runner_install < self_heal
    assert "Zero-touch core + GitHub runner autostart + self-heal installed" in text
