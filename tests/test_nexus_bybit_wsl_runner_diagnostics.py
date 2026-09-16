from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_nexus_bybit_wsl_runner_diagnostics.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-bybit-wsl-runner-diagnostics.yml"


def test_runner_diagnostics_are_read_only_and_redacted():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "NEXUS Bybit WSL Runner" in text
    assert "/opt/nexus-bybit-runner/_diag" not in text  # constructed only from pinned runner root
    assert "Runner.Listener|Runner.Worker|dotnet" in text
    assert "Runner\\.Worker" in text and "Runner\\.Listener" in text
    assert "Protect-DiagnosticLine" in text
    assert "[redacted]" in text
    assert "[opaque]" in text
    assert "raw_diagnostic_files_uploaded = $false" in text
    assert "runner_mutation_performed = $false" in text
    assert "windows_runner_paths_modified = $false" in text
    assert "bybit_private_credentials_used = $false" in text
    for forbidden in (
        "Register-ScheduledTask",
        "Start-ScheduledTask",
        "Stop-ScheduledTask",
        "Unregister-ScheduledTask",
        "config.sh",
        "run.sh",
        "actions/runner-registration-token",
    ):
        assert forbidden not in text


def test_wsl_probe_uses_lf_only_stdin_transport_with_a_bounded_process() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    invoke = text.split("function Invoke-WslCapture", 1)[1].split(
        "function Protect-DiagnosticLine", 1
    )[0]

    assert '$Command.Replace("`r`n", "`n").Replace("`r", "`n")' in invoke
    assert '$psi.Arguments = "-d $Distribution -u root -- bash -s"' in invoke
    assert "$psi.RedirectStandardInput = $true" in invoke
    assert "$previousConsoleInputEncoding = [Console]::InputEncoding" in invoke
    assert '[Console]::InputEncoding = (New-Object System.Text.UTF8Encoding($false))' in invoke
    assert "[Console]::InputEncoding = $previousConsoleInputEncoding" in invoke
    assert "$process.StandardInput.Encoding.GetPreamble().Length -ne 0" in invoke
    assert "$process.StandardInput.Write($normalizedCommand)" in invoke
    assert "$process.StandardInput.Close()" in invoke
    assert "$process.WaitForExit(30000)" in invoke
    assert "$process.Kill()" in invoke
    assert "bash -lc $Command" not in invoke


def test_diagnostic_signal_scan_is_recent_and_bounded() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    signals = text.split("$diagSignalsCommand = @'", 1)[1].split("'@", 1)[0]

    assert "for prefix in Runner Worker" in signals
    assert "recent_files=()" in signals
    assert '[ "${#recent_files[@]}" -gt 8 ]' in signals
    assert 'recent_files=("${recent_files[@]:1}")' in signals
    assert "lines_read=$((lines_read + 1))" in signals
    assert '[ "$lines_read" -ge 2500 ] && break' in signals

    bash = shutil.which("bash")
    if not bash:
        pytest.skip("Bash syntax validation is unavailable")
    completed = subprocess.run(
        [bash, "-n"],
        input=signals.replace("__RUNNER_ROOT__", "/opt/nexus-bybit-runner"),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell check is Windows-only")
def test_capture_script_parses_and_bom_free_encoding_is_supported_on_windows() -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    assert powershell, "Windows PowerShell is required on windows-latest"
    escaped = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null;$errors=$null;"
        f"[System.Management.Automation.Language.Parser]::ParseFile('{escaped}',[ref]$tokens,[ref]$errors)|Out-Null;"
        "if($errors.Count -gt 0){$errors|ForEach-Object{Write-Error $_.Message};exit 1};"
        "$original=[Console]::InputEncoding;"
        "$encoding=(New-Object System.Text.UTF8Encoding($false));"
        "try{[Console]::InputEncoding=$encoding;"
        "if([Console]::InputEncoding.GetPreamble().Length -ne 0){exit 2}}"
        "finally{[Console]::InputEncoding=$original}"
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


def test_runner_diagnostics_workflow_is_bounded_to_failures_and_physical_windows():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflows: ["NEXUS persistent Paper trading loop"]' in text
    assert "github.event.workflow_run.conclusion == 'failure'" in text
    assert "github.event.workflow_run.conclusion == 'cancelled'" in text
    assert "github.event_name != 'workflow_dispatch'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "runs-on: [self-hosted, Windows, X64, nexus-remote-rescue]" in text
    assert "permissions:\n  contents: read" in text
    assert "nexus-bybit-wsl-runner-diagnostics-${{" in text
    assert "github.event.workflow_run.id" in text
    assert "cancel-in-progress: false" in text
    assert "uses:" not in text.split("  capture:", 1)[1]
    assert "actions/checkout@" not in text
    assert "actions/upload-artifact@" not in text
    assert "Prepare exact diagnostic source without JavaScript actions" in text
    assert "git -c credential.helper= -c http.https://github.com/.extraheader= fetch --no-tags --prune --depth=1 $repoUrl $env:GITHUB_SHA" in text
    assert "$env:GIT_TERMINAL_PROMPT = '0'" in text
    assert "$env:GCM_INTERACTIVE = 'Never'" in text
    assert "git checkout --force --detach FETCH_HEAD" in text
    assert "diagnostic_anonymous_public_fetch=true" in text
    assert "diagnostic_javascript_actions_used=false" in text
    assert "Publish sanitized runner diagnostics to job log" in text
    assert "sanitized_diagnostics_log_begin" in text
    assert "sanitized_diagnostics_log_end" in text
    assert "raw_diagnostic_files_uploaded=false" in text
    assert "runner_mutation_performed=false" in text
    assert "windows_runner_paths_modified=false" in text
    assert "bybit_private_credentials_used=false" in text
    assert "capture_nexus_bybit_wsl_runner_diagnostics.ps1" in text
