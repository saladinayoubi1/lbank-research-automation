from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = ROOT / "scripts" / "nexus_windows_autostart.ps1"
CMD = ROOT / "INSTALL_NEXUS_AUTOSTART.cmd"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_autostart_registers_current_user_logon_task_without_elevation():
    text = read(PS)
    for marker in (
        "NEXUS-ZeroTouch-Autopilot",
        "New-ScheduledTaskTrigger -AtLogOn",
        "New-ScheduledTaskPrincipal",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "-MultipleInstances IgnoreNew",
        "-RestartCount 999",
        "-StartWhenAvailable",
        "-ExecutionTimeLimit ([TimeSpan]::Zero)",
        "Register-ScheduledTask",
        "Start-ScheduledTask",
    ):
        assert marker in text
    assert "-RunLevel Highest" not in text
    assert "NT AUTHORITY\\SYSTEM" not in text


def test_daemon_runs_real_local_supervisor_hidden_and_recovers_it():
    text = read(PS)
    for marker in (
        "local_node_supervisor.py",
        "--poll-seconds",
        "--with-dashboard",
        "pythonw.exe",
        "-WindowStyle Hidden",
        "Get-SupervisorProcess",
        "Start-LocalSupervisor",
        "local_supervisor_start_failed",
        "duplicate_daemon_rejected",
    ):
        assert marker in text


def test_phase7_resume_is_state_driven_and_never_auto_prepares_new_mission():
    text = read(PS)
    for marker in (
        "nexus.phase7-local-session.v1",
        "phase7_fail_closed_multiple_active_sessions",
        "phase7_waiting_for_required_reboot",
        "phase7_waiting_for_full_disconnect",
        "phase7_offline_conditions_satisfied",
        "Invoke-Phase7Mode $Root 'ExecuteOffline' $id",
        "phase7_waiting_for_github_reconnect",
        "Invoke-Phase7Mode $Root 'SubmitReturn' $id",
        "phase7_return_pr_already_exists_no_duplicate_submit",
    ):
        assert marker in text
    assert "Invoke-Phase7Mode $Root 'PrepareOnline'" not in text


def test_offline_execution_requires_dual_target_unreachable_and_post_reboot_state():
    text = read(PS)
    for marker in (
        "Test-TcpTarget 'api.github.com' 443",
        "Test-TcpTarget '1.1.1.1' 443",
        "internet_unavailable = (-not $github -and -not $secondary)",
        "LastBootUpTime",
        "prepared_at",
    ):
        assert marker in text


def test_one_click_installer_only_delegates_to_versioned_powershell_installer():
    text = read(CMD)
    assert "scripts\\nexus_windows_autostart.ps1" in text
    assert "-Mode Install" in text
    assert "-RepoRoot" in text
    assert "curl" not in text.casefold()
    assert "gh auth login" not in text.casefold()
