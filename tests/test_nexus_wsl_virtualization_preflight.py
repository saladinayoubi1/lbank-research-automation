from __future__ import annotations

import os
import subprocess
from pathlib import Path


SCRIPT = Path("scripts/diagnose_nexus_wsl_virtualization.ps1")
WORKFLOW = Path(".github/workflows/nexus-wsl-virtualization-preflight.yml")


def test_preflight_preserves_windows_runner_and_never_reboots_automatically() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "windows_runner_paths_modified = $false" in text
    assert "automatic_restart_performed = $false" in text
    assert "Restart-Computer" not in text
    assert "shutdown.exe" not in text


def test_preflight_distinguishes_firmware_boot_and_restart_blockers() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for decision in (
        "FIRMWARE_VIRTUALIZATION_DISABLED",
        "WSL2_SLAT_UNAVAILABLE",
        "HYPERVISOR_BOOT_FLAG_REPAIRED_RESTART_REQUIRED",
        "WINDOWS_RESTART_REQUIRED_FOR_VIRTUALIZATION",
        "HYPERVISOR_NOT_ACTIVE_RESTART_REQUIRED",
        "VIRTUALIZATION_PREFLIGHT_READY",
    ):
        assert decision in text
    assert "VirtualizationFirmwareEnabled" in text
    assert "HypervisorPresent" in text
    assert "hypervisorlaunchtype" in text
    assert "PendingFileRenameOperations" in text


def test_preflight_has_wmi_independent_processor_feature_probe() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "IsProcessorFeaturePresent" in text
    assert "PF_SECOND_LEVEL_ADDRESS_TRANSLATION = 20" in text
    assert "PF_VIRT_FIRMWARE_ENABLED = 21" in text
    assert "native_processor_features" in text
    assert "HKLM:\\HARDWARE\\DESCRIPTION\\System\\CentralProcessor\\0" in text


def test_preflight_uses_isolated_disposable_wsl2_probe() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "NEXUS-WSL2-PROBE-" in text
    assert "NEXUS\\WSLProbe" in text
    assert "'--import', $probeName" in text
    assert "'--unregister', $probeName" in text
    assert "cleanup_complete" in text
    assert "transient_service_start_attempted" in text
    assert "sc.exe" in text


def test_preflight_workflow_is_bounded_to_main_and_explicit_marker() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "branches:\n      - main" in text
    assert "[diagnose-wsl-virtualization]" in text
    assert "runs-on: [self-hosted, Windows, X64]" in text
    assert "permissions:\n  contents: read" in text
    assert "actions: write" not in text


def test_preflight_script_parses_on_windows_powershell() -> None:
    if os.name != "nt":
        return
    command = (
        "$tokens=$null; $errors=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        "'scripts\\diagnose_nexus_wsl_virtualization.ps1',"
        "[ref]$tokens,[ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
    )
