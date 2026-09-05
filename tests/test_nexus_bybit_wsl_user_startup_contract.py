from __future__ import annotations

from pathlib import Path
import subprocess
import sys


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "install_nexus_bybit_wsl_user_startup.ps1"
)


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _function(text: str, name: str, next_name: str) -> str:
    start = text.index(f"function {name}")
    end = text.index(f"function {next_name}", start)
    return text[start:end]


def _command_here_string(function_block: str) -> str:
    start_marker = "$command = @'\n"
    start = function_block.index(start_marker) + len(start_marker)
    end = function_block.index("\n'@", start)
    return function_block[start:end]


def test_process_liveness_probe_uses_procfs_exact_argv0_without_pgrep() -> None:
    text = _script()
    probe = _function(text, "Get-RunnerProcessState", "Test-Listener")

    assert "pgrep -f" not in text
    assert "/proc/self/cmdline" in probe
    assert "/proc/[0-9]*" in probe
    assert "IFS= read -r -d ''" in probe
    assert "'__RUNNER_ROOT__/bin/Runner.Listener'" in probe
    assert "'__RUNNER_ROOT__/bin/Runner.Worker'" in probe
    assert "$command.Replace('__RUNNER_ROOT__', $RunnerRoot)" in probe
    assert "runner_process_probe_unparsable=true" in probe
    assert "known = $false" in probe


def test_idle_listener_recycle_rechecks_worker_before_each_kill() -> None:
    text = _script()
    recycle = _function(text, "Stop-IdleExternalListener", "Start-ManagedRunnerProcess")

    assert "/proc/self/cmdline" in recycle
    assert "/proc/[0-9]*" in recycle
    assert "worker_present()" in recycle
    # Declaration + initial guard + guard immediately before a Listener kill.
    assert recycle.count("worker_present") >= 3
    assert "'__RUNNER_ROOT__/bin/Runner.Worker'" in recycle
    assert "'__RUNNER_ROOT__/bin/Runner.Listener'" in recycle
    assert "$command.Replace('__RUNNER_ROOT__', $RunnerRoot)" in recycle
    listener_match = recycle.index("'__RUNNER_ROOT__/bin/Runner.Listener'")
    second_worker_guard = recycle.index("if worker_present; then", listener_match)
    kill = recycle.index("kill -TERM", listener_match)
    assert second_worker_guard < kill
    assert "exit 23" in recycle
    assert "exit 24" in recycle


def test_embedded_bash_probe_commands_parse_on_unix() -> None:
    if sys.platform == "win32":
        return

    text = _script()
    blocks = (
        _function(text, "Get-RunnerProcessState", "Test-Listener"),
        _function(text, "Stop-IdleExternalListener", "Start-ManagedRunnerProcess"),
    )
    for block in blocks:
        command = _command_here_string(block).replace(
            "__RUNNER_ROOT__", "/opt/nexus-bybit-runner"
        )
        subprocess.run(
            ["bash", "-n", "-c", command],
            check=True,
            capture_output=True,
            text=True,
        )


def test_startup_script_parses_with_windows_powershell() -> None:
    if sys.platform != "win32":
        return

    path = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{path}', "
        "[ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )


def test_unknown_probe_and_active_worker_paths_remain_fail_closed() -> None:
    text = _script()

    assert "managed_child_state_unknown_no_interrupt=true" in text
    assert "existing_runner_worker_active_waiting=true" in text
    assert "managed_child_worker_active_no_interrupt=true" in text
    assert "unknown_probe_interrupt_allowed = $false" in text
    assert "active_worker_interrupt_allowed = $false" in text
    assert "Write-Host 'unknown_probe_interrupt_allowed=false'" in text
    assert "Write-Host 'active_worker_interrupt_allowed=false'" in text


def test_recovery_contract_preserves_authority_and_identity_boundaries() -> None:
    text = _script()

    assert "Distribution must remain pinned to Ubuntu." in text
    assert "RunnerRoot must remain pinned." in text
    assert "ExpectedRunnerName must remain pinned." in text
    assert "this script will not create or replace it" in text

    for marker in (
        "task_scheduler_used = $false",
        "runner_registration_modified = $false",
        "runner_credentials_modified = $false",
        "windows_acl_modified = $false",
        "windows_service_modified = $false",
        "private_exchange_credentials_used = $false",
        "live_trading_authority_changed = $false",
    ):
        assert marker in text

    forbidden_mutators = (
        "Register-ScheduledTask",
        "schtasks.exe",
        "config.sh --url",
        "config.sh remove",
        "icacls.exe",
        "New-Service",
        "Set-Service",
    )
    for token in forbidden_mutators:
        assert token not in text
