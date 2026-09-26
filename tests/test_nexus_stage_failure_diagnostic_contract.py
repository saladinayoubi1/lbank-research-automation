"""Fail-closed static contract for bounded stage-only supervisor diagnostics."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_and_smoke_nexus_personal_pro.ps1"


def _diagnostic_block() -> str:
    source = SCRIPT.read_text(encoding="utf-8")
    return source.split("# Before normal fail-closed removal", 1)[1].split(
        "    try { Stop-SmokeProcesses } catch { }", 1
    )[0]


def test_stage_failure_snapshot_is_scratch_only_bounded_and_categorical() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    block = _diagnostic_block()
    assert "Test-PathWithin $script:SmokeRoot $env:RUNNER_TEMP" in block
    assert "^nexus-app-smoke-[0-9]+$" in block
    assert "product-data" in block and "supervisor-state.json" in block
    assert block.count("ReparsePoint") == 3
    assert "$stateInfo.Length -le 65536" in block
    assert "source_matches = $null" in block  # Missing source is unknown, not mismatch.
    assert "$reason.Length -gt 4096" in block
    assert "$script:Evidence['smoke_failure_diagnostic'] = $diag" in block
    assert "$diag.reason =" not in block
    assert "$diag.raw" not in block
    assert "Get-ChildItem" not in block
    assert "$env:APPDATA" not in block
    assert "$env:LOCALAPPDATA" not in block
    assert source.index("smoke_failure_diagnostic'] = $diag") < source.rindex(
        "    try { Stop-SmokeProcesses } catch { }"
    ) < source.rindex("    try { Remove-SmokeRoot } catch { }")
    assert "UNSAFE_LEGACY_OWNER_ACTIVATION_DISABLED" in source


def test_failure_categories_do_not_publish_raw_startup_reason() -> None:
    block = _diagnostic_block()
    for classification in (
        "module_import", "missing_file", "permission", "port_collision",
        "gateway_timeout", "restart_limit", "sidecar_exit",
        "untrusted_state_file", "diagnostic_unavailable",
    ):
        assert f"$diag.failure_class = '{classification}'" in block
    assert "smoke_failure_diagnostic = $reason" not in block
    assert "smoke_failure_diagnostic = $state" not in block


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell 5.1 parser")
def test_installer_parses_in_owner_compatible_windows_powershell() -> None:
    literal_path = str(SCRIPT).replace("'", "''")
    code = (
        "$tokens=$null; $errors=$null; "
        f"[Management.Automation.Language.Parser]::ParseFile('{literal_path}',"
        "[ref]$tokens,[ref]$errors)|Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { Write-Error $_.Message }; exit 2 }"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    assert result.returncode == 0, result.stderr
