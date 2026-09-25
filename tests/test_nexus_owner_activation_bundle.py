from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_nexus_owner_activation_bundle.ps1"


def test_bundle_gate_is_read_only_and_cannot_authorize_activation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for expected in (
        "READ_ONLY_BUNDLE_PASS_NOT_ACTIVATION",
        "official_main_provenance_externally_verified = $false",
        "full_real_owner_profile_tested = $false",
        "process_quiescence_tested = $false",
        "rollback_tested = $false",
        "activation_authorized = $false",
        "owner_modified = $false",
    ):
        assert expected in source
    for forbidden in (
        "Stop-Process", "Start-Process", "Move-Item", "Copy-Item",
        "Remove-Item", "Set-Content", "Set-ItemProperty", "Register-ScheduledTask",
        "-ActivateInstalledBuild", "CloseMainWindow", "Restart-Computer",
    ):
        assert forbidden not in source


def test_backup_paths_and_every_backup_domain_are_verified() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for expected in (
        "BACKUP_PATH_TRAVERSAL", "BACKUP_REPARSE_POINT", "BACKUP_ROOT_REPARSE_POINT", "BACKUP_PATH_OUTSIDE_ROOT",
        "STAGE_PROOF_HASH_MISMATCH", "STAGE_PHYSICAL_PROOF_INVALID",
        "STAGE_SOURCE_OR_AUTHORITY_MISMATCH", "BACKUP_MANIFEST_COUNT_MISMATCH",
        "DUPLICATE_BACKUP_DATA_ENTRY", "BACKUP_DATA_LENGTH_MISMATCH",
        "BACKUP_JOURNAL_HASH_MISMATCH", "ORIGINAL_OWNER_JOURNAL",
        "DUPLICATE_SHORTCUT_ENTRY", "UNEXPECTED_SHORTCUT_PATH",
        "BACKUP_SHORTCUT_HASH_MISMATCH", "LIVE_SHORTCUT_RETARGETED",
        "DUPLICATE_PAPER_SYNC_ENTRY", "BACKUP_PAPER_SYNC_HASH_MISMATCH",
        "LIVE_PAPER_SYNC_HASH_MISMATCH",
    ):
        # Hash mismatch codes are formed by the reusable ExactHash helper.
        if expected.endswith("_HASH_MISMATCH"):
            assert expected.removesuffix("_HASH_MISMATCH") in source
            assert "$Code + '_HASH_MISMATCH'" in source
        else:
            assert expected in source
    assert "$expectedShortcuts -contains [string]$link.original_path" in source
    assert "$expectedRelative -contains [string]$entry.relative" in source
    assert "ExpectedStageProofSha256" in source


def test_bundle_gate_is_never_invoked_by_automatic_installer() -> None:
    root = SCRIPT.parents[1]
    installer = (root / "scripts" / "install_and_smoke_nexus_personal_pro.ps1").read_text(encoding="utf-8")
    fastpath = (root / ".github" / "workflows" / "nexus-install-app-fastpath.yml").read_text(encoding="utf-8")
    assert SCRIPT.name not in installer
    assert SCRIPT.name not in fastpath
    assert "UNSAFE_LEGACY_OWNER_ACTIVATION_DISABLED" in installer
    assert "-ActivateInstalledBuild" not in fastpath


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell parser proof")
def test_bundle_gate_parses_on_windows() -> None:
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    assert ps
    escaped = str(SCRIPT).replace("'", "''")
    check = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',"
        "[ref]$tokens,[ref]$errors)|Out-Null;"
        "if(@($errors).Count){$errors|ForEach-Object{$_.Message};exit 1}"
    )
    subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", check],
                   check=True, capture_output=True, text=True)


@pytest.mark.skipif(os.name != "nt", reason="Pure safety-helper fault injection runs on Windows")
def test_bundle_helper_rejects_sandbox_traversal_and_corrupt_sha(tmp_path: Path) -> None:
    # Extract only pure read-only helpers; never execute the laptop-specific owner preflight.
    source = SCRIPT.read_text(encoding="utf-8")
    helpers = "function Require" + source.split("function Require", 1)[1].split("function Read-Manifest", 1)[0]
    inside = tmp_path / "inside.txt"
    inside.write_text("fixture", encoding="utf-8")
    import hashlib
    digest = hashlib.sha256(inside.read_bytes()).hexdigest()
    root = str(tmp_path).replace("'", "''")
    code = (
        "$ErrorActionPreference='Stop';\n" + helpers + "\n"
        f"$p=UnderRoot '{root}' 'inside.txt';"
        f"ExactHash $p '{digest}' 'FIXTURE';"
        f"try {{ UnderRoot '{root}' '..\\outside.txt' | Out-Null;"
        "throw 'TRAVERSAL_NOT_REJECTED' } catch {"
        "if($_.Exception.Message -ne 'BACKUP_PATH_TRAVERSAL'){throw} };"
        f"try {{ ExactHash $p '{'0' * 64}' 'FIXTURE';"
        "throw 'HASH_NOT_REJECTED' } catch {"
        "if($_.Exception.Message -ne 'FIXTURE_HASH_MISMATCH'){throw} };"
        "Write-Output 'SANDBOX_FAULT_INJECTION_PASS'"
    )
    ps = shutil.which("powershell.exe") or shutil.which("powershell")
    assert ps
    result = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-Command", code],
                            check=True, text=True, capture_output=True)
    assert "SANDBOX_FAULT_INJECTION_PASS" in result.stdout
