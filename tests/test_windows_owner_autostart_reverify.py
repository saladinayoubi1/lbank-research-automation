from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
VERIFIER = ROOT / "scripts" / "verify_nexus_owner_autostart.ps1"
TARGET = ROOT / ".nexus" / "owner-autostart-proof-target.txt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_owner_proof_target_is_one_exact_sha() -> None:
    value = read(TARGET).strip()
    assert re.fullmatch(r"[0-9a-f]{40}", value)


def test_owner_proof_privacy_guard_does_not_overwrite_powershell_home() -> None:
    text = read(WORKFLOW)
    assert "$userHome=" in text
    assert "$root -eq $userHome" in text
    assert "$root.StartsWith($userHome +" in text
    assert "$home=" not in text.casefold()
    assert "permissions:\n  contents: read" in text


def test_owner_task_query_is_read_only_and_reports_native_failure_deterministically() -> None:
    text = read(VERIFIER)
    for marker in (
        "$previousErrorActionPreference = $ErrorActionPreference",
        "$ErrorActionPreference = 'Continue'",
        "$output = @(& $schtasks /Query /TN $Name /XML 2>&1)",
        "$exitCode = $LASTEXITCODE",
        "$ErrorActionPreference = $previousErrorActionPreference",
        "scheduled task query failed for $Name exit=$exitCode output=$detail",
        "task_scheduler_read_only = $true",
        "task_registration_modified = $false",
        "elevation_requested = $false",
    ):
        assert marker in text
    lowered = text.casefold()
    for forbidden in ("/create", "/delete", "/change", "register-scheduledtask", "unregister-scheduledtask", "-verb runas"):
        assert forbidden not in lowered


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell parser check is Windows-only")
def test_owner_autostart_verifier_parses_with_windows_powershell() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")
    escaped = str(VERIFIER).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
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
