from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_remote_installer_does_not_use_reserved_args_parameter() -> None:
    text = (ROOT / "scripts" / "install_nexus_autostart_from_runner.ps1").read_text(encoding="utf-8-sig")
    assert "[string[]]$Args" not in text
    assert "[string[]]$GitArgs" in text
    assert "@GitArgs" in text


def test_autostart_installers_have_non_cim_scheduler_fallback() -> None:
    for rel in (
        "scripts/nexus_windows_autostart.ps1",
        "scripts/nexus_github_runner_autostart.ps1",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8-sig")
        assert "Install-LogonTaskViaCom" in text
        assert "New-Object -ComObject 'Schedule.Service'" in text
        assert "RegisterTaskDefinition" in text
        assert "scheduled_tasks_cim_unavailable_using_com_fallback" in text


def test_remote_evidence_snapshot_has_com_fallback() -> None:
    text = (ROOT / "scripts" / "install_nexus_autostart_from_runner.ps1").read_text(encoding="utf-8-sig")
    assert "Get-ScheduledTask -TaskName $Name -ErrorAction Stop" in text
    assert "GetFolder('\\').GetTask($Name)" in text
