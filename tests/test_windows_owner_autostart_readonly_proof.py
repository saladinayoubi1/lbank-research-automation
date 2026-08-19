import os
import platform
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VERIFIER = ROOT / "scripts" / "verify_nexus_owner_autostart.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"
TARGET = ROOT / ".nexus" / "owner-autostart-proof-target.txt"


def test_owner_autostart_verifier_is_strictly_read_only():
    text = VERIFIER.read_text(encoding="utf-8")
    forbidden = (
        "Register-ScheduledTask",
        "Unregister-ScheduledTask",
        "Set-ScheduledTask",
        "Start-ScheduledTask",
        "Stop-ScheduledTask",
        "New-ScheduledTaskAction",
        "New-ScheduledTaskTrigger",
        "New-ScheduledTaskPrincipal",
        "Get-ScheduledTask",
        "Get-ScheduledTaskInfo",
        "config.cmd",
        ".credentials",
        "/Create",
        "/Change",
        "/Delete",
        "/Run",
        "/End",
    )
    for token in forbidden:
        assert token not in text
    assert "schtasks.exe" in text
    assert "/Query /TN $Name /XML" in text
    assert "task_scheduler_query_transport = 'schtasks_xml'" in text
    assert "expected Limited/LeastPrivilege" in text
    assert "expected Interactive" in text
    assert "owner_profile_file_content_read = $false" in text
    assert "task_registration_modified = $false" in text
    assert "runner_registration_modified = $false" in text
    assert "live_trading_authority = $false" in text
    assert "paper_only = $true" in text


def test_owner_autostart_verifier_binds_both_expected_tasks_and_scripts():
    text = VERIFIER.read_text(encoding="utf-8")
    assert "NEXUS-ZeroTouch-Autopilot" in text
    assert "NEXUS-GitHub-Runner-Autostart" in text
    assert "nexus_windows_autostart.ps1" in text
    assert "nexus_github_runner_autostart.ps1" in text
    assert "-Mode\\s+RunDaemon" in text
    assert "\\NEXUS\\lbank-research-automation" in text
    assert "InteractiveToken" in text
    assert "LeastPrivilege" in text


def test_owner_autostart_proof_target_is_exact_sha():
    value = TARGET.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"[0-9a-f]{40}", value)
    assert value == "b076688f1bad031bd6899727d728d08bdfa1596a"


def test_local_runner_wires_readonly_proof_without_permission_expansion():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text
    assert "issues: write" not in text
    assert "statuses: write" not in text
    assert "[verify-owner-autostart]" in text
    assert "scripts\\verify_nexus_owner_autostart.ps1" in text
    assert "nexus-owner-autostart-proof-${{ github.run_id }}" in text
    assert "if: always() && github.event_name == 'push'" in text


def test_owner_autostart_verifier_powershell_syntax_on_windows():
    if platform.system() != "Windows":
        return
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::ParseFile($env:NEXUS_VERIFIER_PATH,[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|ForEach-Object{Write-Error $_};exit 1}",
    ]
    env = os.environ.copy()
    env["NEXUS_VERIFIER_PATH"] = str(VERIFIER)
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr