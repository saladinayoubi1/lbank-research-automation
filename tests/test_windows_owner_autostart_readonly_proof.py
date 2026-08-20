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
    forbidden=("Register-ScheduledTask","Unregister-ScheduledTask","Set-ScheduledTask","Start-ScheduledTask","Stop-ScheduledTask","New-ScheduledTaskAction","New-ScheduledTaskTrigger","New-ScheduledTaskPrincipal","Get-ScheduledTask","Get-ScheduledTaskInfo","config.cmd",".credentials","/Create","/Change","/Delete","/Run","/End")
    for token in forbidden: assert token not in text
    assert "schtasks.exe" in text and "/Query /TN $Name /XML" in text
    assert "task_registration_modified = $false" in text and "runner_registration_modified = $false" in text
    assert "live_trading_authority = $false" in text and "paper_only = $true" in text

def test_owner_autostart_verifier_binds_both_expected_tasks_and_scripts():
    text=VERIFIER.read_text(encoding="utf-8")
    for token in ("NEXUS-ZeroTouch-Autopilot","NEXUS-GitHub-Runner-Autostart","nexus_windows_autostart.ps1","nexus_github_runner_autostart.ps1","InteractiveToken","LeastPrivilege"): assert token in text

def test_owner_autostart_proof_target_is_exact_sha():
    value=TARGET.read_text(encoding="utf-8").strip(); assert re.fullmatch(r"[0-9a-f]{40}",value); assert value=="4da70f0a375817424a712117ccfe88c8b9d013be"

def test_local_runner_wires_readonly_proof_without_permission_expansion():
    text=WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read\n" in text and "issues: write" not in text and "statuses: write" not in text
    assert "[verify-owner-autostart]" in text and "scripts\\verify_nexus_owner_autostart.ps1" in text

def test_owner_autostart_verifier_powershell_syntax_on_windows():
    if platform.system() != "Windows": return
    command=["powershell.exe","-NoProfile","-NonInteractive","-Command","$e=$null;$t=$null;[System.Management.Automation.Language.Parser]::ParseFile($env:NEXUS_VERIFIER_PATH,[ref]$t,[ref]$e)|Out-Null;if($e.Count){$e|ForEach-Object{Write-Error $_};exit 1}"]
    env=os.environ.copy(); env["NEXUS_VERIFIER_PATH"]=str(VERIFIER)
    result=subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True,timeout=30); assert result.returncode==0,result.stdout+result.stderr
