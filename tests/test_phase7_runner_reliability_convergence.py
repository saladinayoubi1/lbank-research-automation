from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "nexus_runtime_worker.js"
STAGER = ROOT / "desktop" / "nexus-product" / "stage-package-resources.js"
PACKAGE = ROOT / "desktop" / "nexus-product" / "package.json"
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


def test_packaged_owner_bootstrap_uses_canonical_core_without_automatic_self_heal() -> None:
    stager = STAGER.read_text(encoding="utf-8")
    bootstrap = BOOTSTRAP_MAIN.read_text(encoding="utf-8")
    package = json.loads(PACKAGE.read_text(encoding="utf-8"))

    assert "copyScript('install_nexus_owner_autostart_from_gui.ps1');" in stager
    assert "install_nexus_owner_autostart_with_self_heal.ps1" not in stager
    assert "install_nexus_owner_autostart_core.ps1" not in stager
    assert "scriptName: 'install_nexus_owner_autostart_from_gui.ps1'" in bootstrap

    resources = {(row.get("from"), row.get("to")) for row in package["build"]["extraResources"]}
    assert ("sidecar/install_nexus_owner_autostart_from_gui.ps1", "scripts/install_nexus_owner_autostart_from_gui.ps1") in resources
    assert not any("install_nexus_owner_autostart_core.ps1" in str(value) for row in resources for value in row)


def test_manual_canonical_install_does_not_enable_self_heal() -> None:
    text = MANUAL_INSTALL.read_text(encoding="utf-8")
    assert "nexus_github_runner_autostart.ps1" in text
    assert "enable_nexus_runner_self_heal.ps1" not in text
    assert "Runner self-heal is intentionally not enabled automatically." in text
    assert "Zero-touch core + GitHub runner autostart installed" in text
