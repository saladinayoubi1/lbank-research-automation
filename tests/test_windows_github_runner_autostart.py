from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER_PS = ROOT / "scripts" / "nexus_github_runner_autostart.ps1"
INSTALLER = ROOT / "INSTALL_NEXUS_AUTOSTART.cmd"
WORKFLOW = ROOT / ".github" / "workflows" / "nexus-local-runner.yml"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_repository_really_uses_windows_x64_self_hosted_runner():
    text = read(WORKFLOW)
    assert "runs-on: [self-hosted, Windows, X64]" in text


def test_runner_discovery_requires_config_credentials_binary_and_exact_repo_binding():
    text = read(RUNNER_PS)
    for marker in (
        "https://github.com/saladinayoubi1/lbank-research-automation",
        "'.runner'",
        "'.credentials'",
        "'run.cmd'",
        "'bin\\Runner.Listener.exe'",
        "PSObject.Properties['gitHubUrl']",
        "runner_fail_closed_multiple_configured_installations",
        "runner_unavailable_no_unique_configured_installation",
    ):
        assert marker in text
    assert "Get-Content -LiteralPath $credentialsPath" not in text
    assert "config.cmd" not in text


def test_existing_official_windows_runner_service_is_preferred_and_never_duplicated():
    text = read(RUNNER_PS)
    for marker in (
        "actions.runner.*",
        "Get-CimInstance Win32_Service",
        "Get-ServiceForRunner",
        "runner_service_running",
        "Start-Service",
        "runner_service_stopped_requires_admin",
    ):
        assert marker in text
    service_pos = text.index("$service = Get-ServiceForRunner $runner")
    listener_pos = text.index("$listener = Get-ListenerProcess $runner", service_pos)
    assert service_pos < listener_pos


def test_interactive_runner_listener_is_hidden_supervised_and_rate_limited():
    text = read(RUNNER_PS)
    for marker in (
        "Runner.Listener.exe",
        "$env:ComSpec",
        "CreateNoWindow = $true",
        "runner_listener_start_requested",
        "runner_listener_running",
        "Get-ListenerProcess",
        "TotalSeconds -lt 60",
        "duplicate_runner_daemon_rejected",
    ):
        assert marker in text


def test_runner_task_is_current_user_logon_limited_and_no_credentials_are_added():
    text = read(RUNNER_PS)
    for marker in (
        "NEXUS-GitHub-Runner-Autostart",
        "New-ScheduledTaskTrigger -AtLogOn",
        "-LogonType Interactive",
        "-RunLevel Limited",
        "-MultipleInstances IgnoreNew",
        "-RestartCount 999",
        "-StartWhenAvailable",
        "Register-ScheduledTask",
        "Start-ScheduledTask",
        "registration_preserved=true",
    ):
        assert marker in text
    lowered = text.casefold()
    assert "-runlevel highest" not in lowered
    assert "nt authority\\system" not in lowered
    assert "gh auth login" not in lowered
    assert "personalaccesstoken" not in lowered
    assert "registration-token" not in lowered


def test_runner_discovery_is_bounded_not_whole_disk_recursive():
    text = read(RUNNER_PS)
    assert "Desktop\\actions-runner" in text
    assert "Downloads\\actions-runner" in text
    assert "Get-ChildItem -LiteralPath $parent -Directory -Filter 'actions-runner*'" in text
    assert "-Recurse" not in text


def test_one_click_installer_installs_core_and_runner_autostart():
    text = read(INSTALLER)
    assert "scripts\\nexus_windows_autostart.ps1" in text
    assert "scripts\\nexus_github_runner_autostart.ps1" in text
    assert text.count("-Mode Install") == 2
    assert "GitHub runner autostart installation failed" in text
    assert "no CMD or PowerShell window is required" in text
