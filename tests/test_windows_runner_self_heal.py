from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELF_HEAL = ROOT / "scripts" / "enable_nexus_runner_self_heal.ps1"
REGISTER = ROOT / "REGISTER_NEXUS_RUNNER.cmd"
ENTRYPOINT = ROOT / "ENABLE_NEXUS_RUNNER_SELF_HEAL.cmd"


def test_self_heal_reuses_existing_runner_task_without_new_watchdog() -> None:
    text = SELF_HEAL.read_text(encoding="utf-8")
    for marker in (
        "NEXUS-GitHub-Runner-Autostart",
        "creates_separate_watchdog_task = $false",
        "creates_background_watchdog_process = $false",
        "RegisterTaskDefinition",
        "MultipleInstances -ne 2",
        "existing_task_reused = $true",
    ):
        assert marker in text
    assert "New-ScheduledTask" not in text
    assert "Register-ScheduledTask" not in text
    assert "Start-Job" not in text


def test_self_heal_adds_idempotent_five_minute_daily_repetition() -> None:
    text = SELF_HEAL.read_text(encoding="utf-8")
    for marker in (
        "$TriggerId = 'NEXUS-Self-Heal-5m'",
        "$triggers.Remove($i)",
        "$triggers.Create(2)",
        "$selfHeal.DaysInterval = 1",
        "$selfHeal.Repetition.Interval = 'PT5M'",
        "$selfHeal.Repetition.Duration = 'P1D'",
        "$selfHeal.Repetition.StopAtDurationEnd = $false",
    ):
        assert marker in text


def test_self_heal_preserves_runner_authority_and_credentials() -> None:
    text = SELF_HEAL.read_text(encoding="utf-8")
    for marker in (
        "runner_registration_modified = $false",
        "credentials_modified = $false",
        "elevation_requested = $false",
        "service_installed = $false",
        "paper_only = $true",
        "live_trading_authority = $false",
    ):
        assert marker in text


def test_registration_and_one_click_entrypoints_include_self_heal() -> None:
    register = REGISTER.read_text(encoding="utf-8")
    entry = ENTRYPOINT.read_text(encoding="utf-8")
    assert "enable_nexus_runner_self_heal.ps1" in register
    assert "enable_nexus_runner_self_heal.ps1" in entry
    assert "powershell.exe -NoProfile -ExecutionPolicy Bypass" in entry
