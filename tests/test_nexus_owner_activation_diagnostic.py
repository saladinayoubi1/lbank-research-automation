from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_nexus_owner_activation.ps1"


def test_activation_diagnostic_has_exact_owner_and_stage_provenance_gates() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for marker in (
        "ExpectedOwnerSourceSha", "ExpectedOwnerJournalSha256",
        "ExpectedStageSourceSha", "ExpectedStageArtifactId",
        "STAGED_PACKAGE_PROVENANCE_OR_AUTHORITY_MISMATCH",
        "STAGE_PROOF_NOT_TRUSTED", "STAGED_PACKAGE_INCOMPLETE",
        "OWNER_PAPER_OR_LIVE_CONTRACT_UNSAFE", "OWNER_SHORTCUT_TARGET_MISMATCH",
        "OWNER_JOURNAL_SHA_MISMATCH", "OWNER_ORIGIN_NOT_LOOPBACK",
        "STAGED_ONLY_OWNER_PRESERVED", "PAPER_JOURNAL_VERIFIED_SHORTCUT_ROLLBACK_NOT_VERIFIED",
        "READ_ONLY_DIAGNOSTIC_NOT_ACTIVATION",
        "activation_authorized=$false",
    ):
        assert marker in script

def test_activation_diagnostic_does_not_mutate_owner_or_claim_respawn_proof() -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    for forbidden in (
        "Stop-Process", "Start-Process", "Remove-Item", "Copy-Item",
        "Set-Content", "Set-ItemProperty", "RegisterTaskDefinition",
        "New-NexusShortcut", "-ActivateInstalledBuild",
    ):
        assert forbidden not in script
    assert "Get-Process 'NEXUS Personal Pro','nexus-product-server'" in script
    assert "Schedule.Service" in script
    assert "NEXUS-ZeroTouch-Autopilot" in script
    assert "shutdown_or_respawn_experiment_performed=$false" in script
    assert "official_main_provenance_externally_verified=$false" in script
    assert "owner_processes_mutated=$false" in script
    assert "owner_files_mutated=$false" in script

@pytest.mark.skipif(os.name != "nt", reason="Owner PowerShell parser check runs on Windows")
def test_activation_diagnostic_parses_in_windows_powershell() -> None:
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    assert ps
    escaped = str(SCRIPT).replace("'", "''")
    code = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if(@($errors).Count){$errors|ForEach-Object{$_.Message};exit 1}"
    )
    subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", code],
                   text=True, capture_output=True, check=True)
