from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    ROOT / "scripts" / "install_nexus_autostart_from_runner.ps1",
    ROOT / "scripts" / "nexus_windows_autostart.ps1",
    ROOT / "scripts" / "nexus_github_runner_autostart.ps1",
)


def test_windows_autostart_scripts_do_not_depend_on_os_environment_variable() -> None:
    for path in FILES:
        text = path.read_text(encoding="utf-8-sig")
        assert "$env:OS -ne 'Windows_NT'" not in text
        assert "[Environment]::OSVersion.Platform" in text
        assert "[PlatformID]::Win32NT" in text
