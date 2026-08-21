from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNER = ROOT / "scripts" / "install_nexus_owner_autostart_from_gui.ps1"
COMPAT = ROOT / "scripts" / "nexus_task_scheduler_compat.ps1"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_owner_bootstrap_recovers_only_from_cim_scheduledtasks_failure() -> None:
    text = read(OWNER)
    assert "CimJob_BrokenCimSession" in text
    assert "Cannot connect to CIM server" in text
    assert "Install-TaskViaComFallback $RelativeScript" in text
    assert "task_scheduler_transport=com_fallback" in text
    assert "task_scheduler_cim_fallback_used" in text
    assert "if ($message -notmatch" in text
    assert "{ throw }" in text


def test_com_fallback_preserves_current_user_limited_logon_contract() -> None:
    text = read(COMPAT)
    for marker in (
        "Schedule.Service",
        "TASK_TRIGGER_LOGON = 9",
        "TASK_ACTION_EXEC = 0",
        "TASK_CREATE_OR_UPDATE = 6",
        "TASK_LOGON_INTERACTIVE_TOKEN = 3",
        "TASK_RUNLEVEL_LUA = 0",
        "TASK_INSTANCES_IGNORE_NEW = 2",
        "StartWhenAvailable = $true",
        "DisallowStartIfOnBatteries = $false",
        "StopIfGoingOnBatteries = $false",
        "RestartInterval = 'PT1M'",
        "RestartCount = 999",
        "ExecutionTimeLimit = 'PT0S'",
        "RegisterTaskDefinition",
        "WorkingDirectory = $WorkingDirectory",
        "run_level = $runLevel",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "runas" not in lowered
    assert "highestavailable" not in lowered
    assert "task_logon_password" not in lowered
    assert "set-executionpolicy" not in lowered


def test_owner_com_fallback_installs_both_existing_daemons_without_widening_authority() -> None:
    text = read(OWNER)
    for marker in (
        "NEXUS-ZeroTouch-Autopilot",
        "NEXUS-GitHub-Runner-Autostart",
        "nexus_windows_autostart.ps1",
        "nexus_github_runner_autostart.ps1",
        "-Mode RunDaemon",
        "New-NexusInteractiveLogonTask",
        "network_credentials_added = $false",
        "runner_registration_modified = $false",
        "machine_execution_policy_modified = $false",
        "elevation_requested = $false",
        "live_trading_authority = $false",
        "paper_only = $true",
    ):
        assert marker in text


def test_task_verification_is_cim_independent_after_fallback() -> None:
    owner = read(OWNER)
    assert "Get-NexusScheduledTaskSnapshot $Name" in owner
    snapshot_section = owner[owner.index("function Task-Snapshot"): owner.index("try {", owner.index("function Task-Snapshot"))]
    assert "Get-ScheduledTask" not in snapshot_section
    assert "Get-ScheduledTaskInfo" not in snapshot_section
