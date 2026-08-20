from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "scripts" / "install_nexus_owner_autostart_from_gui.ps1"
ENTRY = ROOT / "desktop" / "nexus-product" / "bootstrap-main.js"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_owner_bootstrap_native_commands_are_judged_by_exit_code_not_stderr() -> None:
    text = read(OWNER)
    for marker in (
        "function Invoke-NativeCapture",
        "$previous = $ErrorActionPreference",
        "$ErrorActionPreference = 'Continue'",
        "$rows = @(& $Executable @Arguments 2>&1)",
        "$exitCode = $LASTEXITCODE",
        "$ErrorActionPreference = $previous",
        "if ($exitCode -ne 0)",
        "native_commands_judged_by_exit_code = $true",
        "Invoke-NativeCapture -Executable $git",
        "Invoke-NativeCapture -Executable $ps",
    ):
        assert marker in text
    assert text.index("$ErrorActionPreference = 'Continue'") < text.index("$rows = @(& $Executable @Arguments 2>&1)")
    assert text.index("$exitCode = $LASTEXITCODE") < text.index("$ErrorActionPreference = $previous")


def test_owner_bootstrap_stays_exact_source_fail_closed_and_non_elevating() -> None:
    text = read(OWNER)
    for marker in (
        "refs/heads/nexus-package-source",
        "--update-shallow",
        "Assert-CanonicalRemote $ManagedRepoRoot",
        "Assert-TrackedClean $ManagedRepoRoot",
        "managed checkout has tracked owner changes; refusing automatic replacement",
        "network_credentials_added = $false",
        "runner_registration_modified = $false",
        "machine_execution_policy_modified = $false",
        "elevation_requested = $false",
        "live_trading_authority = $false",
        "paper_only = $true",
    ):
        assert marker in text
    lowered = text.casefold()
    for forbidden in (
        "config.cmd",
        "--token",
        "personalaccesstoken",
        "github_token",
        "-verb runas",
        "set-executionpolicy",
        "reset --hard",
        "git clean",
        "remove-item -recurse",
    ):
        assert forbidden not in lowered


def test_packaged_gui_supervises_runner_and_retries_owner_bootstrap_boundedly() -> None:
    text = read(ENTRY)
    for marker in (
        "RUNNER_SUPERVISOR_INTERVAL_MS = 60 * 1000",
        "OWNER_AUTOSTART_RETRY_LIMIT = 3",
        "OWNER_AUTOSTART_RETRY_DELAY_MS = 15 * 1000",
        "runnerBootstrapInFlight",
        "setInterval(() => { void reconcileRunnerFromGui(); }, RUNNER_SUPERVISOR_INTERVAL_MS)",
        "app.once('before-quit', () => clearInterval(timer))",
        "startRunnerColdBootstrap().catch",
        "startOwnerAutostartBootstrap(sourceSha).catch",
        "owner_bootstrap_exhausted",
    ):
        assert marker in text
    assert "shell: true" not in text
    assert "config.cmd" not in text.casefold()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 native stderr contract is Windows-only")
def test_windows_powershell_native_stderr_with_zero_exit_does_not_trip_wrapper(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        pytest.skip("Windows PowerShell is unavailable")

    text = read(OWNER)
    start = text.index("function Sanitize-Inline")
    end = text.index("function Get-Git")
    functions = text[start:end]
    probe = functions + r'''
$ErrorActionPreference = 'Stop'
$ok = Invoke-NativeCapture $env:ComSpec '' @('/d','/s','/c','echo normal-stderr 1>&2 & exit /b 0') 'zero-exit-probe'
if ($ok.ExitCode -ne 0) { exit 11 }
if ($ok.Text -notmatch 'normal-stderr') { exit 12 }
$rejected = $false
try {
    [void](Invoke-NativeCapture $env:ComSpec '' @('/d','/s','/c','echo real-failure 1>&2 & exit /b 7') 'nonzero-probe')
}
catch {
    if ($_.Exception.Message -match 'exit=7') { $rejected = $true }
}
if (-not $rejected) { exit 13 }
exit 0
'''
    script = tmp_path / "native-stderr-probe.ps1"
    script.write_text(probe, encoding="utf-8")
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell Git argv binding is Windows-only")
def test_windows_powershell_git_wrapper_preserves_explicit_argument_vector(tmp_path: Path) -> None:
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell or not shutil.which("git"):
        pytest.skip("Windows PowerShell or Git is unavailable")

    text = read(OWNER)
    start = text.index("function Sanitize-Inline")
    end = text.index("function Assert-InteractiveOwner")
    functions = text[start:end]
    root = str(ROOT).replace("'", "''")
    probe = functions + rf'''
$ErrorActionPreference = 'Stop'
$version = Invoke-GitGlobal -GitArguments @('--version')
if ($version -notmatch '^git version ') {{ exit 21 }}
$top = Invoke-Git -Root '{root}' -GitArguments @('rev-parse','--show-toplevel')
if (-not $top) {{ exit 22 }}
exit 0
'''
    script = tmp_path / "git-argv-probe.ps1"
    script.write_text(probe, encoding="utf-8")
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
